"""AR/AP application services (US-8: create and issue customer invoices)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from accounting_shared.exceptions import (
    ConflictError,
    NotFoundError,
    ValidationError,
)
from ar_ap_service.config import ArApSettings
from ar_ap_service.modules.ar_ap.application.dto import (
    CreateInvoiceCommand,
    InvoiceLineInput,
    UpdateInvoiceCommand,
)
from ar_ap_service.modules.ar_ap.domain.entities import (
    AccountInfo,
    Customer,
    Invoice,
    InvoiceLine,
    InvoiceStatus,
    JournalLineInput,
)
from ar_ap_service.modules.ar_ap.domain.repository import (
    AccountReader,
    CustomerRepository,
    InvoiceRepository,
    LedgerPoster,
)

_ZERO = Decimal("0.00")
_REVENUE_TYPE = "revenue"


class InvoiceService:
    """Orchestrates the invoice lifecycle: draft → issue → immutable.

    A draft invoice never touches the ledger. Issuing computes the totals,
    assigns an invoice number and posts a single balanced journal entry inside
    the caller's database transaction.
    """

    def __init__(
        self,
        *,
        invoices: InvoiceRepository,
        customers: CustomerRepository,
        accounts: AccountReader,
        ledger: LedgerPoster,
        settings: ArApSettings,
    ) -> None:
        self._invoices = invoices
        self._customers = customers
        self._accounts = accounts
        self._ledger = ledger
        self._settings = settings

    # ── customers ──────────────────────────────────────────────────────────────

    async def create_customer(self, customer: Customer) -> Customer:
        if not customer.name or not customer.name.strip():
            raise ValidationError("Customer name is required.")
        return await self._customers.add(customer)

    async def list_customers(self, tenant_id: UUID) -> list[Customer]:
        return await self._customers.list_by_tenant(tenant_id)

    async def get_customer(self, tenant_id: UUID, customer_id: UUID) -> Customer:
        customer = await self._customers.get_by_id(tenant_id, customer_id)
        if customer is None:
            raise NotFoundError("Customer not found.")
        return customer

    async def build_invoice_pdf(self, tenant_id: UUID, invoice_id: UUID) -> tuple[bytes, str]:
        """Return PDF bytes and a download filename for an issued invoice."""
        from ar_ap_service.modules.ar_ap.application.pdf_generator import generate_invoice_pdf

        invoice = await self.get_invoice(tenant_id, invoice_id)
        if not invoice.is_posted:
            raise ValidationError("PDF is only available for issued invoices.")
        customer = None
        if invoice.customer_id is not None:
            customer = await self._customers.get_by_id(tenant_id, invoice.customer_id)
        pdf_bytes = generate_invoice_pdf(invoice, customer)
        filename = f"{invoice.invoice_number or invoice.id}.pdf"
        return pdf_bytes, filename

    # ── reads ────────────────────────────────────────────────────────────────

    async def get_invoice(self, tenant_id: UUID, invoice_id: UUID) -> Invoice:
        invoice = await self._invoices.get_by_id(tenant_id, invoice_id)
        if invoice is None:
            raise NotFoundError("Invoice not found.")
        return invoice

    async def list_invoices(
        self,
        tenant_id: UUID,
        *,
        status: str | None = None,
        customer_id: UUID | None = None,
        issued_from: date | None = None,
        issued_to: date | None = None,
    ) -> list[Invoice]:
        if status is not None and status not in set(InvoiceStatus):
            raise ValidationError(f"Unknown invoice status: {status!r}.")
        return await self._invoices.list_by_tenant(
            tenant_id,
            status=status,
            customer_id=customer_id,
            issued_from=issued_from,
            issued_to=issued_to,
        )

    # ── create / update draft ─────────────────────────────────────────────────

    async def create_draft(
        self,
        tenant_id: UUID,
        command: CreateInvoiceCommand,
        created_by: UUID | None,
    ) -> Invoice:
        self._validate_dates(command.issue_date, command.due_date)
        await self._ensure_customer(tenant_id, command.customer_id)
        lines = await self._build_lines(tenant_id, command.lines)

        invoice = Invoice(
            tenant_id=tenant_id,
            customer_id=command.customer_id,
            invoice_number="",
            issue_date=command.issue_date,
            due_date=command.due_date,
            status=InvoiceStatus.DRAFT,
            created_by=created_by,
            created_at=datetime.utcnow(),
            lines=lines,
        )
        invoice.recalculate_totals()
        return await self._invoices.add(invoice)

    async def update_draft(
        self,
        tenant_id: UUID,
        invoice_id: UUID,
        command: UpdateInvoiceCommand,
    ) -> Invoice:
        invoice = await self.get_invoice(tenant_id, invoice_id)
        if invoice.status != InvoiceStatus.DRAFT:
            raise ConflictError(
                "Only draft invoices can be edited. "
                "Issue a credit note to correct an issued invoice."
            )

        new_customer = command.customer_id or invoice.customer_id
        new_issue = command.issue_date or invoice.issue_date
        new_due = command.due_date or invoice.due_date
        self._validate_dates(new_issue, new_due)
        if command.customer_id is not None:
            await self._ensure_customer(tenant_id, command.customer_id)

        invoice.customer_id = new_customer
        invoice.issue_date = new_issue
        invoice.due_date = new_due
        if command.lines is not None:
            invoice.lines = await self._build_lines(tenant_id, command.lines)
        invoice.recalculate_totals()
        invoice.updated_at = datetime.utcnow()
        return await self._invoices.update(invoice)

    async def delete_draft(self, tenant_id: UUID, invoice_id: UUID) -> None:
        invoice = await self.get_invoice(tenant_id, invoice_id)
        if invoice.status != InvoiceStatus.DRAFT:
            raise ConflictError("Only draft invoices can be deleted.")
        await self._invoices.delete(invoice)

    # ── issue ──────────────────────────────────────────────────────────────────

    async def issue_invoice(
        self,
        tenant_id: UUID,
        invoice_id: UUID,
        issued_by: UUID | None,
    ) -> Invoice:
        """Issue a draft invoice and post its balanced journal entry atomically.

        Steps (all within the caller's transaction):
        tenant check → draft check → line check → recompute totals →
        generate number → post journal entry → mark issued.

        If posting fails (e.g. closed period), the exception propagates and the
        surrounding transaction rolls back, so the invoice stays a draft.
        """
        invoice = await self.get_invoice(tenant_id, invoice_id)

        if invoice.status != InvoiceStatus.DRAFT:
            # Requirement 17: prevent double-issue.
            raise ConflictError("Invoice has already been issued.")
        if not invoice.lines:
            raise ValidationError("Cannot issue an invoice with no lines.")
        if invoice.issue_date is None or invoice.due_date is None:
            raise ValidationError("Invoice must have an issue date and due date.")
        self._validate_dates(invoice.issue_date, invoice.due_date)

        invoice.recalculate_totals()
        if invoice.total <= _ZERO:
            raise ValidationError("Invoice total must be greater than zero to issue.")

        revenue_accounts = await self._resolve_revenue_accounts(tenant_id, invoice.lines)
        ar_account = await self._require_account_by_code(
            tenant_id, self._settings.ar_control_account_code, "Accounts Receivable"
        )
        gst_account: AccountInfo | None = None
        if invoice.gst_amount > _ZERO:
            gst_account = await self._require_account_by_code(
                tenant_id, self._settings.gst_output_account_code, "GST Output Tax"
            )

        journal_lines = self._build_journal_lines(
            invoice, ar_account, revenue_accounts, gst_account
        )

        reference = await self._generate_invoice_number(tenant_id, invoice.issue_date)

        journal_entry_id = await self._ledger.post_journal_entry(
            tenant_id=tenant_id,
            entry_date=invoice.issue_date,
            reference=reference,
            description=f"Invoice {reference}",
            source_id=str(invoice.id),
            created_by=issued_by,
            lines=journal_lines,
        )

        invoice.invoice_number = reference
        invoice.status = InvoiceStatus.ISSUED
        invoice.journal_entry_id = journal_entry_id
        invoice.updated_at = datetime.utcnow()
        return await self._invoices.update(invoice)

    # ── helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _validate_dates(issue_date: date | None, due_date: date | None) -> None:
        if issue_date is not None and due_date is not None and due_date < issue_date:
            raise ValidationError("due_date must not be earlier than issue_date.")

    async def _ensure_customer(self, tenant_id: UUID, customer_id: UUID) -> None:
        customer = await self._customers.get_by_id(tenant_id, customer_id)
        if customer is None:
            raise ValidationError("Customer not found for this tenant.")

    async def _build_lines(
        self,
        tenant_id: UUID,
        line_inputs: list[InvoiceLineInput],
    ) -> list[InvoiceLine]:
        if not line_inputs:
            raise ValidationError("An invoice must have at least one line.")
        lines: list[InvoiceLine] = []
        for raw in line_inputs:
            if raw.quantity <= 0:
                raise ValidationError("Line quantity must be greater than zero.")
            if raw.unit_price < 0:
                raise ValidationError("Line unit_price must not be negative.")
            if raw.gst_rate < 0:
                raise ValidationError("Line gst_rate must not be negative.")
            account = await self._accounts.get_by_id(tenant_id, raw.account_id)
            if account is None:
                raise ValidationError(f"Account {raw.account_id} not found for this tenant.")
            if not account.is_active:
                raise ValidationError(f"Account {account.code} is not active.")
            if account.account_type != _REVENUE_TYPE:
                raise ValidationError(
                    f"Account {account.code} is not a revenue account; "
                    "invoice lines must post to revenue accounts."
                )
            line = InvoiceLine(
                account_id=raw.account_id,
                quantity=raw.quantity,
                unit_price=raw.unit_price,
                description=raw.description,
                gst_rate=raw.gst_rate,
            )
            line.recalculate()
            lines.append(line)
        return lines

    async def _resolve_revenue_accounts(
        self,
        tenant_id: UUID,
        lines: list[InvoiceLine],
    ) -> dict[UUID, AccountInfo]:
        resolved: dict[UUID, AccountInfo] = {}
        for line in lines:
            if line.account_id in resolved:
                continue
            account = await self._accounts.get_by_id(tenant_id, line.account_id)
            if account is None:
                raise ValidationError(f"Account {line.account_id} not found for this tenant.")
            if account.account_type != _REVENUE_TYPE:
                raise ValidationError(f"Account {account.code} is not a revenue account.")
            resolved[line.account_id] = account
        return resolved

    async def _require_account_by_code(
        self,
        tenant_id: UUID,
        code: str,
        label: str,
    ) -> AccountInfo:
        account = await self._accounts.get_by_code(tenant_id, code)
        if account is None:
            raise ValidationError(
                f"{label} account (code {code}) is not configured for this tenant."
            )
        return account

    def _build_journal_lines(
        self,
        invoice: Invoice,
        ar_account: AccountInfo,
        revenue_accounts: dict[UUID, AccountInfo],
        gst_account: AccountInfo | None,
    ) -> list[JournalLineInput]:
        """Build a balanced set of journal lines for an issued invoice.

        Debit Accounts Receivable for the gross total; credit each revenue
        account for its net amount; credit GST Output Tax for the total GST.
        """
        lines: list[JournalLineInput] = [
            JournalLineInput(
                account_id=str(ar_account.id),
                debit_amount=invoice.total,
                credit_amount=_ZERO,
                description=f"Accounts receivable — invoice {invoice.invoice_number or invoice.id}",
            )
        ]

        revenue_totals: dict[UUID, Decimal] = {}
        for line in invoice.lines:
            revenue_totals[line.account_id] = (
                revenue_totals.get(line.account_id, _ZERO) + line.line_total
            )
        for account_id, net in revenue_totals.items():
            if net <= _ZERO:
                continue
            account = revenue_accounts[account_id]
            lines.append(
                JournalLineInput(
                    account_id=str(account.id),
                    debit_amount=_ZERO,
                    credit_amount=net,
                    description=f"Revenue — {account.name}",
                )
            )

        if invoice.gst_amount > _ZERO:
            if gst_account is None:
                raise ValidationError("GST Output Tax account is required when GST applies.")
            lines.append(
                JournalLineInput(
                    account_id=str(gst_account.id),
                    debit_amount=_ZERO,
                    credit_amount=invoice.gst_amount,
                    description="GST output tax",
                )
            )

        total_debit = sum((line.debit_amount for line in lines), _ZERO)
        total_credit = sum((line.credit_amount for line in lines), _ZERO)
        if total_debit != total_credit:
            raise ValidationError(
                f"Journal entry is not balanced: debit {total_debit}, credit {total_credit}."
            )
        return lines

    async def _generate_invoice_number(self, tenant_id: UUID, issue_date: date) -> str:
        prefix = f"INV-{issue_date.year}-"
        existing = await self._invoices.count_with_number_prefix(tenant_id, prefix)
        return f"{prefix}{existing + 1:04d}"
