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
    CreditNoteLineInput,
    InvoiceLineInput,
    IssueCreditNoteCommand,
    RecordPaymentCommand,
    UpdateInvoiceCommand,
)
from ar_ap_service.modules.ar_ap.domain.entities import (
    AccountInfo,
    CreditNote,
    CreditNoteLine,
    CreditNoteStatus,
    Customer,
    Invoice,
    InvoiceLine,
    InvoiceSettlement,
    InvoiceStatus,
    JournalLineInput,
    Payment,
)
from ar_ap_service.modules.ar_ap.domain.repository import (
    AccountReader,
    CreditNoteRepository,
    CustomerRepository,
    InvoiceRepository,
    LedgerPoster,
    PaymentRepository,
)

_ZERO = Decimal("0.00")
_REVENUE_TYPE = "revenue"
_ASSET_TYPE = "asset"
#: Invoice statuses against which a customer payment may be recorded (US-9).
_PAYABLE_STATUSES: frozenset[InvoiceStatus] = frozenset(
    {InvoiceStatus.ISSUED, InvoiceStatus.PARTIAL, InvoiceStatus.OVERDUE}
)
#: Invoice statuses against which a credit note may be issued (US-10).
#: Drafts are excluded: an unissued invoice has no ledger impact to reverse.
_CREDITABLE_STATUSES: frozenset[InvoiceStatus] = frozenset(
    {InvoiceStatus.ISSUED, InvoiceStatus.PARTIAL, InvoiceStatus.PAID, InvoiceStatus.OVERDUE}
)


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


class PaymentService:
    """Records customer payments against issued invoices (US-9).

    Recording a payment is a single atomic operation: validate the invoice and
    deposit account, compute the outstanding balance, post a balanced journal
    entry (Debit bank/cash, Credit Accounts Receivable), persist the payment with
    its ``journal_entry_id`` and roll the invoice status forward to partial/paid.
    Everything runs on the caller's transaction, so if journal posting fails the
    payment is never saved and the invoice status never changes.
    """

    def __init__(
        self,
        *,
        payments: PaymentRepository,
        invoices: InvoiceRepository,
        customers: CustomerRepository,
        accounts: AccountReader,
        ledger: LedgerPoster,
        settings: ArApSettings,
    ) -> None:
        self._payments = payments
        self._invoices = invoices
        self._customers = customers
        self._accounts = accounts
        self._ledger = ledger
        self._settings = settings

    # ── reads ──────────────────────────────────────────────────────────────────

    async def get_payment(self, tenant_id: UUID, payment_id: UUID) -> Payment:
        payment = await self._payments.get_by_id(tenant_id, payment_id)
        if payment is None:
            raise NotFoundError("Payment not found.")
        return payment

    async def list_invoice_payments(self, tenant_id: UUID, invoice_id: UUID) -> list[Payment]:
        # Enforce tenant ownership of the invoice before exposing its payments.
        await self._require_invoice(tenant_id, invoice_id)
        return await self._payments.list_by_invoice(tenant_id, invoice_id)

    async def list_payments(
        self,
        tenant_id: UUID,
        *,
        invoice_id: UUID | None = None,
        customer_id: UUID | None = None,
        payment_method: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[Payment]:
        return await self._payments.list_by_tenant(
            tenant_id,
            invoice_id=invoice_id,
            customer_id=customer_id,
            payment_method=payment_method,
            date_from=date_from,
            date_to=date_to,
        )

    async def get_invoice_settlement(self, tenant_id: UUID, invoice_id: UUID) -> InvoiceSettlement:
        """Return invoice total and amount already paid (for outstanding balance)."""
        invoice = await self._require_invoice(tenant_id, invoice_id)
        paid = await self._payments.sum_paid_for_invoice(tenant_id, invoice_id)
        return InvoiceSettlement(invoice_total=invoice.total, amount_paid=paid)

    # ── record payment ───────────────────────────────────────────────────────

    async def record_payment(
        self,
        tenant_id: UUID,
        invoice_id: UUID,
        command: RecordPaymentCommand,
        recorded_by: UUID | None,
    ) -> Payment:
        """Record a (full or partial) payment and post its journal entry atomically."""
        # Idempotency: a retry carrying a previously seen key returns the original
        # payment instead of double-posting.
        if command.idempotency_key:
            existing = await self._payments.get_by_idempotency_key(
                tenant_id, command.idempotency_key
            )
            if existing is not None:
                return existing

        invoice = await self._require_invoice(tenant_id, invoice_id)

        if invoice.status == InvoiceStatus.DRAFT:
            raise ConflictError("Cannot record a payment for a draft invoice; issue it first.")
        if invoice.status == InvoiceStatus.PAID:
            raise ConflictError("Invoice is already fully paid.")
        if invoice.status not in _PAYABLE_STATUSES:
            raise ConflictError(
                f"Cannot record a payment for an invoice with status {invoice.status.value!r}."
            )

        amount = command.amount.quantize(_ZERO)
        if amount <= _ZERO:
            raise ValidationError("Payment amount must be greater than zero.")

        already_paid = await self._payments.sum_paid_for_invoice(tenant_id, invoice_id)
        outstanding = invoice.total - already_paid
        if outstanding <= _ZERO:
            raise ConflictError("Invoice is already fully paid.")
        if amount > outstanding:
            raise ValidationError(
                f"Payment amount {amount} exceeds the outstanding balance {outstanding}."
            )

        deposit_account = await self._resolve_deposit_account(tenant_id, command.deposit_account_id)
        ar_account = await self._require_account_by_code(tenant_id)

        if await self._ledger.is_period_closed(tenant_id, command.payment_date):
            raise ConflictError(
                f"Cannot record payment: {command.payment_date} is in a closed accounting period."
            )

        payment = Payment(
            tenant_id=tenant_id,
            invoice_id=invoice.id,
            customer_id=invoice.customer_id,
            amount=amount,
            payment_date=command.payment_date,
            payment_method=command.payment_method,
            reference=command.reference,
            deposit_account_id=deposit_account.id,
            idempotency_key=command.idempotency_key,
            created_by=recorded_by,
            created_at=datetime.utcnow(),
        )

        reference = self._build_journal_reference(invoice, command.reference)
        journal_lines = [
            JournalLineInput(
                account_id=str(deposit_account.id),
                debit_amount=amount,
                credit_amount=_ZERO,
                description=f"Payment received — {deposit_account.name}",
            ),
            JournalLineInput(
                account_id=str(ar_account.id),
                debit_amount=_ZERO,
                credit_amount=amount,
                description=(
                    f"Accounts receivable — invoice {invoice.invoice_number or invoice.id}"
                ),
            ),
        ]

        journal_entry_id = await self._ledger.post_journal_entry(
            tenant_id=tenant_id,
            entry_date=command.payment_date,
            reference=reference,
            description=f"Payment for invoice {invoice.invoice_number or invoice.id}",
            source_id=str(payment.id),
            source_type="payment",
            created_by=recorded_by,
            lines=journal_lines,
        )
        payment.journal_entry_id = journal_entry_id

        saved = await self._payments.add(payment)

        total_paid_after = already_paid + amount
        invoice.status = (
            InvoiceStatus.PAID if total_paid_after >= invoice.total else InvoiceStatus.PARTIAL
        )
        invoice.updated_at = datetime.utcnow()
        await self._invoices.update(invoice)

        return saved

    # ── helpers ──────────────────────────────────────────────────────────────

    async def _require_invoice(self, tenant_id: UUID, invoice_id: UUID) -> Invoice:
        invoice = await self._invoices.get_by_id(tenant_id, invoice_id)
        if invoice is None:
            raise NotFoundError("Invoice not found.")
        return invoice

    async def _resolve_deposit_account(self, tenant_id: UUID, account_id: UUID) -> AccountInfo:
        account = await self._accounts.get_by_id(tenant_id, account_id)
        if account is None:
            raise ValidationError("Deposit account not found for this tenant.")
        if not account.is_active:
            raise ValidationError(f"Deposit account {account.code} is not active.")
        if account.account_type != _ASSET_TYPE:
            raise ValidationError(
                f"Deposit account {account.code} must be an asset (bank/cash) account."
            )
        return account

    async def _require_account_by_code(self, tenant_id: UUID) -> AccountInfo:
        code = self._settings.ar_control_account_code
        account = await self._accounts.get_by_code(tenant_id, code)
        if account is None:
            raise ValidationError(
                f"Accounts Receivable account (code {code}) is not configured for this tenant."
            )
        return account

    @staticmethod
    def _build_journal_reference(invoice: Invoice, payment_reference: str | None) -> str:
        invoice_ref = invoice.invoice_number or str(invoice.id)
        if payment_reference:
            return f"PAY {invoice_ref} / {payment_reference}"
        return f"PAY {invoice_ref}"


class CreditNoteService:
    """Issues credit notes against issued invoices (US-10).

    A credit note corrects, reduces or reverses an already-issued invoice without
    ever editing the original invoice or its journal entry. Issuing is a single
    atomic operation: validate the invoice and revenue accounts, compute the
    creditable amount, post a balanced reversal journal entry (Debit Revenue,
    Debit GST Output, Credit Accounts Receivable) and persist the credit note
    with its ``journal_entry_id``. Everything runs on the caller's transaction, so
    if journal posting fails the credit note is never saved (requirement 12).

    The original invoice's status is intentionally left unchanged: credit-note
    history is exposed separately so US-8/US-9 status workflows keep working.
    """

    def __init__(
        self,
        *,
        credit_notes: CreditNoteRepository,
        invoices: InvoiceRepository,
        customers: CustomerRepository,
        accounts: AccountReader,
        ledger: LedgerPoster,
        settings: ArApSettings,
    ) -> None:
        self._credit_notes = credit_notes
        self._invoices = invoices
        self._customers = customers
        self._accounts = accounts
        self._ledger = ledger
        self._settings = settings

    # ── reads ──────────────────────────────────────────────────────────────────

    async def get_credit_note(self, tenant_id: UUID, credit_note_id: UUID) -> CreditNote:
        credit_note = await self._credit_notes.get_by_id(tenant_id, credit_note_id)
        if credit_note is None:
            raise NotFoundError("Credit note not found.")
        return credit_note

    async def list_invoice_credit_notes(
        self, tenant_id: UUID, invoice_id: UUID
    ) -> list[CreditNote]:
        # Enforce tenant ownership of the invoice before exposing its credit notes.
        await self._require_invoice(tenant_id, invoice_id)
        return await self._credit_notes.list_by_invoice(tenant_id, invoice_id)

    async def list_credit_notes(
        self,
        tenant_id: UUID,
        *,
        invoice_id: UUID | None = None,
        customer_id: UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[CreditNote]:
        return await self._credit_notes.list_by_tenant(
            tenant_id,
            invoice_id=invoice_id,
            customer_id=customer_id,
            date_from=date_from,
            date_to=date_to,
        )

    # ── issue credit note ──────────────────────────────────────────────────────

    async def issue_credit_note(
        self,
        tenant_id: UUID,
        invoice_id: UUID,
        command: IssueCreditNoteCommand,
        issued_by: UUID | None,
    ) -> CreditNote:
        """Issue a credit note and post its balanced reversal journal entry atomically.

        Steps (all within the caller's transaction): idempotency check →
        tenant/invoice check → status check → build & validate lines (revenue
        accounts, tenant-scoped) → compute totals → creditable-amount check →
        closed-period check → generate number → post reversal journal entry →
        persist. If posting fails the exception propagates and the surrounding
        transaction rolls back, so no credit note is saved.
        """
        # Idempotency: a retry carrying a previously seen key returns the original
        # credit note instead of double-posting.
        if command.idempotency_key:
            existing = await self._credit_notes.get_by_idempotency_key(
                tenant_id, command.idempotency_key
            )
            if existing is not None:
                return existing

        invoice = await self._require_invoice(tenant_id, invoice_id)

        if invoice.status == InvoiceStatus.DRAFT:
            raise ConflictError(
                "Cannot issue a credit note for a draft invoice; issue the invoice first."
            )
        if invoice.status not in _CREDITABLE_STATUSES:
            raise ConflictError(
                f"Cannot issue a credit note for an invoice with status {invoice.status.value!r}."
            )

        lines, revenue_accounts = await self._build_lines(tenant_id, command.lines)

        credit_note = CreditNote(
            tenant_id=tenant_id,
            invoice_id=invoice.id,
            customer_id=invoice.customer_id,
            issue_date=command.issue_date,
            reason=command.reason,
            status=CreditNoteStatus.ISSUED,
            idempotency_key=command.idempotency_key,
            created_by=issued_by,
            created_at=datetime.utcnow(),
            lines=lines,
        )
        credit_note.recalculate_totals()

        if credit_note.total <= _ZERO:
            raise ValidationError("Credit note total must be greater than zero.")

        # Requirement 5/9: a credit note may not exceed the invoice value minus
        # what has already been credited against it.
        already_credited = await self._credit_notes.sum_credited_for_invoice(tenant_id, invoice.id)
        creditable = invoice.total - already_credited
        if credit_note.total > creditable:
            raise ValidationError(
                f"Credit note total {credit_note.total} exceeds the remaining creditable "
                f"amount {creditable} for invoice {invoice.invoice_number or invoice.id}."
            )

        ar_account = await self._require_account_by_code(
            tenant_id, self._settings.ar_control_account_code, "Accounts Receivable"
        )
        gst_account: AccountInfo | None = None
        if credit_note.gst_amount > _ZERO:
            gst_account = await self._require_account_by_code(
                tenant_id, self._settings.gst_output_account_code, "GST Output Tax"
            )

        if await self._ledger.is_period_closed(tenant_id, command.issue_date):
            raise ConflictError(
                f"Cannot issue credit note: {command.issue_date} is in a closed accounting period."
            )

        credit_note.credit_note_number = await self._generate_credit_note_number(
            tenant_id, command.issue_date
        )

        journal_lines = self._build_journal_lines(
            credit_note, ar_account, revenue_accounts, gst_account
        )
        reference = self._build_journal_reference(credit_note, invoice)

        journal_entry_id = await self._ledger.post_journal_entry(
            tenant_id=tenant_id,
            entry_date=command.issue_date,
            reference=reference,
            description=(
                f"Credit note {credit_note.credit_note_number} for invoice "
                f"{invoice.invoice_number or invoice.id}"
            ),
            source_id=str(credit_note.id),
            source_type="credit_note",
            created_by=issued_by,
            lines=journal_lines,
            is_reversal=True,
            reversed_entry_id=invoice.journal_entry_id,
        )
        credit_note.journal_entry_id = journal_entry_id

        return await self._credit_notes.add(credit_note)

    # ── helpers ──────────────────────────────────────────────────────────────

    async def _require_invoice(self, tenant_id: UUID, invoice_id: UUID) -> Invoice:
        invoice = await self._invoices.get_by_id(tenant_id, invoice_id)
        if invoice is None:
            raise NotFoundError("Invoice not found.")
        return invoice

    async def _build_lines(
        self,
        tenant_id: UUID,
        line_inputs: list[CreditNoteLineInput],
    ) -> tuple[list[CreditNoteLine], dict[UUID, AccountInfo]]:
        if not line_inputs:
            raise ValidationError("A credit note must have at least one line.")
        lines: list[CreditNoteLine] = []
        revenue_accounts: dict[UUID, AccountInfo] = {}
        for raw in line_inputs:
            if raw.quantity <= 0:
                raise ValidationError("Line quantity must be greater than zero.")
            if raw.unit_price < 0:
                raise ValidationError("Line unit_price must not be negative.")
            if raw.gst_rate < 0:
                raise ValidationError("Line gst_rate must not be negative.")
            account = revenue_accounts.get(raw.account_id)
            if account is None:
                account = await self._accounts.get_by_id(tenant_id, raw.account_id)
                if account is None:
                    raise ValidationError(f"Account {raw.account_id} not found for this tenant.")
                if not account.is_active:
                    raise ValidationError(f"Account {account.code} is not active.")
                if account.account_type != _REVENUE_TYPE:
                    raise ValidationError(
                        f"Account {account.code} is not a revenue account; "
                        "credit note lines must post to revenue accounts."
                    )
                revenue_accounts[raw.account_id] = account
            line = CreditNoteLine(
                account_id=raw.account_id,
                quantity=raw.quantity,
                unit_price=raw.unit_price,
                description=raw.description,
                gst_rate=raw.gst_rate,
                invoice_line_id=raw.invoice_line_id,
            )
            line.recalculate()
            lines.append(line)
        return lines, revenue_accounts

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
        credit_note: CreditNote,
        ar_account: AccountInfo,
        revenue_accounts: dict[UUID, AccountInfo],
        gst_account: AccountInfo | None,
    ) -> list[JournalLineInput]:
        """Build a balanced reversal of the invoice's revenue/GST/AR impact.

        Debit each revenue account for its net amount; debit GST Output Tax for
        the total GST; credit Accounts Receivable for the gross total. This is the
        exact mirror of the invoice posting from US-8.
        """
        lines: list[JournalLineInput] = []

        revenue_totals: dict[UUID, Decimal] = {}
        for line in credit_note.lines:
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
                    debit_amount=net,
                    credit_amount=_ZERO,
                    description=f"Revenue reversal — {account.name}",
                )
            )

        if credit_note.gst_amount > _ZERO:
            if gst_account is None:
                raise ValidationError("GST Output Tax account is required when GST applies.")
            lines.append(
                JournalLineInput(
                    account_id=str(gst_account.id),
                    debit_amount=credit_note.gst_amount,
                    credit_amount=_ZERO,
                    description="GST output tax reversal",
                )
            )

        lines.append(
            JournalLineInput(
                account_id=str(ar_account.id),
                debit_amount=_ZERO,
                credit_amount=credit_note.total,
                description=(f"Accounts receivable — credit note {credit_note.credit_note_number}"),
            )
        )

        total_debit = sum((line.debit_amount for line in lines), _ZERO)
        total_credit = sum((line.credit_amount for line in lines), _ZERO)
        if total_debit != total_credit:
            raise ValidationError(
                f"Journal entry is not balanced: debit {total_debit}, credit {total_credit}."
            )
        return lines

    async def _generate_credit_note_number(self, tenant_id: UUID, issue_date: date) -> str:
        prefix = f"CN-{issue_date.year}-"
        existing = await self._credit_notes.count_with_number_prefix(tenant_id, prefix)
        return f"{prefix}{existing + 1:04d}"

    @staticmethod
    def _build_journal_reference(credit_note: CreditNote, invoice: Invoice) -> str:
        invoice_ref = invoice.invoice_number or str(invoice.id)
        return f"{credit_note.credit_note_number} / {invoice_ref}"
