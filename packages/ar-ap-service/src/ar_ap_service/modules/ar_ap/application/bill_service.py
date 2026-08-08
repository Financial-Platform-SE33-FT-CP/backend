"""Bill (Accounts Payable) application service (US-11 / US-12).

US-11: Record vendor bills (draft → open/recorded).
US-12: Pay bills (record bill payment → update status).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from accounting_shared.exceptions import ConflictError, NotFoundError, ValidationError
from ar_ap_service.modules.ar_ap.domain.entities import (
    AccountInfo,
    Bill,
    BillLine,
    BillPayment,
    BillStatus,
    GstKind,
    GstSourceType,
    GstTransaction,
    JournalLineInput,
    PaymentMethod,
    Vendor,
)
from ar_ap_service.modules.ar_ap.domain.repository import (
    AccountReader,
    BillPaymentRepository,
    BillRepository,
    GstRepository,
    LedgerPoster,
    VendorRepository,
)

_ZERO = Decimal("0.00")
_ASSET_TYPE = "asset"
_EXPENSE_TYPE = "expense"
_PAYABLE_STATUSES: frozenset[BillStatus] = frozenset({BillStatus.OPEN, BillStatus.PARTIAL})
_BILL_GST_KINDS: frozenset[GstKind] = frozenset(
    {
        GstKind.INPUT,
        GstKind.ZERO_RATED,
        GstKind.EXEMPT,
    }
)


def _gst_reporting_period(transaction_date: date) -> str:
    """Return the internal quarterly GST reporting-period identifier."""
    quarter = ((transaction_date.month - 1) // 3) + 1
    return f"{transaction_date.year}-Q{quarter}"


class BillService:
    """Orchestrates the bill lifecycle: draft → record (open) → pay."""

    def __init__(
        self,
        bills: BillRepository,
        vendors: VendorRepository,
        accounts: AccountReader,
        gst: GstRepository,
        ledger: LedgerPoster,
        bill_payments: BillPaymentRepository,
    ) -> None:
        self._bills = bills
        self._vendors = vendors
        self._accounts = accounts
        self._gst = gst
        self._ledger = ledger
        self._bill_payments = bill_payments

    async def create_draft(
        self,
        tenant_id: UUID,
        vendor_id: UUID,
        *,
        issue_date: date,
        due_date: date,
        lines_input: list[dict[str, object]],
        created_by: UUID | None,
    ) -> Bill:
        self._validate_dates(issue_date, due_date)
        vendor = await self._vendors.get_by_id(tenant_id, vendor_id)
        if vendor is None:
            raise ValidationError("Vendor not found for this tenant.")

        bill = Bill(
            tenant_id=tenant_id,
            vendor_id=vendor_id,
            issue_date=issue_date,
            due_date=due_date,
            status=BillStatus.DRAFT,
            created_by=created_by,
        )
        bill.lines = [await self._line_from_input(tenant_id, item) for item in lines_input]
        bill.recalculate_totals()
        return await self._bills.add(bill)

    async def update_draft(
        self,
        tenant_id: UUID,
        bill_id: UUID,
        *,
        vendor_id: UUID | None = None,
        issue_date: date | None = None,
        due_date: date | None = None,
        lines_input: list[dict[str, object]] | None = None,
    ) -> Bill:
        bill = await self._require_draft(tenant_id, bill_id)
        if vendor_id is not None:
            vendor = await self._vendors.get_by_id(tenant_id, vendor_id)
            if vendor is None:
                raise ValidationError("Vendor not found for this tenant.")
            bill.vendor_id = vendor_id
        if issue_date is not None:
            bill.issue_date = issue_date
        if due_date is not None:
            bill.due_date = due_date
        if issue_date is not None:
            bill.issue_date = issue_date
        if bill.issue_date is not None and bill.due_date is not None:
            self._validate_dates(bill.issue_date, bill.due_date)
        if lines_input is not None:
            bill.lines = [await self._line_from_input(tenant_id, item) for item in lines_input]
        bill.recalculate_totals()
        return await self._bills.update(bill)

    async def record_bill(
        self,
        tenant_id: UUID,
        bill_id: UUID,
        created_by: UUID | None,
    ) -> Bill:
        bill = await self._require_draft(tenant_id, bill_id)
        await self._validate_accounts(tenant_id, bill)
        entry_date = bill.issue_date
        if entry_date is None:
            raise ValidationError("Bill issue date is required.")
        if await self._ledger.is_period_closed(tenant_id, entry_date):
            raise ConflictError(f"Cannot record bill: {entry_date} is in a closed period.")

        bill.recalculate_totals()
        ap_account = await self._require_ap_account(tenant_id)
        lines: list[JournalLineInput] = []
        for line in bill.lines:
            acc = await self._accounts.get_by_id(tenant_id, line.account_id)
            if acc is None:
                raise ValidationError(f"Account {line.account_id} not found for this tenant.")
            line_total = line.line_total
            gst = line.gst_amount
            lines.append(
                JournalLineInput(
                    account_id=str(line.account_id),
                    debit_amount=line_total,
                    description=line.description or "Bill expense",
                )
            )
            if gst > _ZERO:
                gst_account = await self._require_gst_account(tenant_id)
                lines.append(
                    JournalLineInput(
                        account_id=str(gst_account.id),
                        debit_amount=gst,
                        description="GST input tax",
                    )
                )
        lines.append(
            JournalLineInput(
                account_id=str(ap_account.id),
                credit_amount=bill.total,
                description=f"Bill {bill.bill_number or bill.id}",
            )
        )
        bill_number = await self._next_bill_number(tenant_id)
        entry_id = await self._ledger.post_journal_entry(
            tenant_id=tenant_id,
            entry_date=entry_date,
            reference=bill_number,
            description=f"Bill {bill_number}",
            source_id=str(bill.id),
            created_by=created_by,
            lines=lines,
            source_type="bill",
        )
        bill.bill_number = bill_number
        bill.journal_entry_id = entry_id
        bill.status = BillStatus.OPEN

        gst_transactions = self._build_gst_transactions(bill)
        await self._gst.add_transactions(gst_transactions)

        return await self._bills.update(bill)

    async def delete_draft(self, tenant_id: UUID, bill_id: UUID) -> None:
        bill = await self._require_draft(tenant_id, bill_id)
        await self._bills.delete(bill)

    async def get_bill(self, tenant_id: UUID, bill_id: UUID) -> Bill:
        bill = await self._bills.get_by_id(tenant_id, bill_id)
        if bill is None:
            raise NotFoundError("Bill not found.")
        return bill

    async def list_bills(
        self,
        tenant_id: UUID,
        *,
        status: str | None = None,
        vendor_id: UUID | None = None,
        issued_from: date | None = None,
        issued_to: date | None = None,
    ) -> list[Bill]:
        return await self._bills.list_by_tenant(
            tenant_id,
            status=status,
            vendor_id=vendor_id,
            issued_from=issued_from,
            issued_to=issued_to,
        )

    # ── vendor helpers ────────────────────────────────────────────────────────

    async def create_vendor(self, tenant_id: UUID, name: str, email: str | None = None) -> Vendor:
        vendor = Vendor(tenant_id=tenant_id, name=name, email=email)
        return await self._vendors.add(vendor)

    async def list_vendors(self, tenant_id: UUID) -> list[Vendor]:
        return await self._vendors.list_by_tenant(tenant_id)

    # ── bill payment (US-12) ───────────────────────────────────────────────────

    async def pay_bill(
        self,
        tenant_id: UUID,
        bill_id: UUID,
        *,
        payment_date: date,
        amount: Decimal,
        payment_method: PaymentMethod,
        reference: str | None,
        payment_account_id: UUID,
        created_by: UUID | None,
    ) -> Bill:
        bill = await self._require_bill(tenant_id, bill_id)
        if bill.status not in _PAYABLE_STATUSES:
            raise ConflictError(f"Cannot pay a bill with status {bill.status.value!r}.")

        if amount <= _ZERO:
            raise ValidationError("Payment amount must be greater than zero.")

        already_paid = await self._bill_payments.sum_paid_for_bill(tenant_id, bill_id)
        outstanding = bill.total - already_paid
        if outstanding <= _ZERO:
            raise ConflictError("Bill is already fully paid.")
        if amount > outstanding:
            raise ValidationError(f"Payment amount {amount} exceeds outstanding {outstanding}.")

        bank_account = await self._require_bank_account(tenant_id, payment_account_id)
        ap_account = await self._require_ap_account(tenant_id)

        if await self._ledger.is_period_closed(tenant_id, payment_date):
            raise ConflictError(f"Cannot record payment: {payment_date} is in a closed period.")

        payment = BillPayment(
            bill_id=bill_id,
            tenant_id=tenant_id,
            vendor_id=bill.vendor_id,
            amount=amount,
            payment_date=payment_date,
            payment_method=payment_method,
            reference=reference,
            payment_account_id=payment_account_id,
            created_by=created_by,
        )

        lines: list[JournalLineInput] = [
            JournalLineInput(
                account_id=str(ap_account.id),
                debit_amount=amount,
                description=f"Bill payment — {bank_account.name}",
            ),
            JournalLineInput(
                account_id=str(bank_account.id),
                credit_amount=amount,
                description=f"Bill {bill.bill_number or bill.id} payment",
            ),
        ]
        journal_entry_id = await self._ledger.post_journal_entry(
            tenant_id=tenant_id,
            entry_date=payment_date,
            reference=f"PAY-{str(bill.id)[:8]}",
            description=f"Payment for bill {bill.bill_number or bill.id}",
            source_id=str(payment.id),
            created_by=created_by,
            lines=lines,
            source_type="bill_payment",
        )
        payment.journal_entry_id = journal_entry_id
        await self._bill_payments.add(payment)

        remaining = outstanding - amount
        if remaining <= _ZERO:
            bill.status = BillStatus.PAID
        else:
            bill.status = BillStatus.PARTIAL
        return await self._bills.update(bill)

    async def get_bill_settlement(self, tenant_id: UUID, bill_id: UUID) -> tuple[Decimal, Decimal]:
        bill = await self._require_bill(tenant_id, bill_id)
        paid = await self._bill_payments.sum_paid_for_bill(tenant_id, bill_id)
        return bill.total, paid

    async def list_bill_payments(self, tenant_id: UUID, bill_id: UUID) -> list[BillPayment]:
        return await self._bill_payments.list_by_bill(tenant_id, bill_id)

    # ── AP aging ──────────────────────────────────────────────────────────────

    async def get_ap_aging(
        self, tenant_id: UUID, as_of: date | None = None
    ) -> list[dict[str, object]]:
        bills = await self._bills.list_by_tenant(tenant_id)
        cutoff = as_of or date.today()
        rows: list[dict[str, object]] = []
        for bill in bills:
            if bill.status in (BillStatus.PAID, BillStatus.VOID, BillStatus.DRAFT):
                continue
            paid = await self._bill_payments.sum_paid_for_bill(tenant_id, bill.id)
            outstanding = bill.total - paid
            if outstanding <= _ZERO:
                continue
            days = (cutoff - bill.due_date).days if bill.due_date else 0
            bucket = "current"
            if days > 90:
                bucket = "90plus"
            elif days > 60:
                bucket = "61_90"
            elif days > 30:
                bucket = "31_60"
            elif days > 0:
                bucket = "1_30"
            rows.append(
                {
                    "bill_id": str(bill.id),
                    "vendor_id": str(bill.vendor_id) if bill.vendor_id else None,
                    "bill_number": bill.bill_number,
                    "due_date": bill.due_date.isoformat() if bill.due_date else None,
                    "bill_total": str(bill.total),
                    "amount_paid": str(paid),
                    "outstanding": str(outstanding),
                    "days_overdue": max(days, 0),
                    "aging_bucket": bucket,
                }
            )
        return rows

    # ── internal helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _validate_dates(issue: date, due: date) -> None:
        if due < issue:
            raise ValidationError("Due date cannot be earlier than issue date.")

    async def _line_from_input(
        self,
        tenant_id: UUID,
        item: dict[str, object],
    ) -> BillLine:
        raw_account_id = str(item["account_id"])
        account_id = UUID(raw_account_id) if raw_account_id else UUID(int=0)

        raw_gst_code_id = item.get("gst_code_id")
        gst_code_id = UUID(str(raw_gst_code_id)) if raw_gst_code_id else None
        gst_rate = Decimal(str(item.get("gst_rate", 0)))

        if gst_code_id is not None:
            gst_code = await self._gst.get_code_by_id(tenant_id, gst_code_id)
            if gst_code is None:
                raise ValidationError(f"GST code {gst_code_id} not found for this tenant.")
            if not gst_code.is_active:
                raise ValidationError(f"GST code {gst_code.code} is not active.")
            if gst_code.gst_kind not in _BILL_GST_KINDS:
                raise ValidationError(f"GST code {gst_code.code} cannot be used on a bill.")
            gst_rate = gst_code.rate
        elif gst_rate > _ZERO:
            raise ValidationError("GST code is required for a bill line with GST.")

        line = BillLine(
            account_id=account_id,
            quantity=Decimal(str(item.get("quantity", 1))),
            unit_price=Decimal(str(item.get("unit_price", 0))),
            description=str(item.get("description")) if item.get("description") else None,
            gst_code_id=gst_code_id,
            gst_rate=gst_rate,
        )
        line.recalculate()
        return line

    async def _require_draft(self, tenant_id: UUID, bill_id: UUID) -> Bill:
        bill = await self._bills.get_by_id(tenant_id, bill_id)
        if bill is None:
            raise NotFoundError("Bill not found.")
        if bill.status != BillStatus.DRAFT:
            raise ConflictError(f"Bill is already recorded (status: {bill.status.value}).")
        return bill

    async def _require_bill(self, tenant_id: UUID, bill_id: UUID) -> Bill:
        bill = await self._bills.get_by_id(tenant_id, bill_id)
        if bill is None:
            raise NotFoundError("Bill not found.")
        return bill

    async def _require_ap_account(self, tenant_id: UUID) -> AccountInfo:
        ap_code = "2000"
        ap = await self._accounts.get_by_code(tenant_id, ap_code)
        if ap is None:
            raise ValidationError(
                f"AP control account (code {ap_code}) not configured for this tenant."
            )
        return ap

    async def _require_gst_account(self, tenant_id: UUID) -> AccountInfo:
        gst_code = "1200"
        gst = await self._accounts.get_by_code(tenant_id, gst_code)
        if gst is None:
            raise ValidationError(f"GST Input account (code {gst_code}) not configured.")
        return gst

    async def _require_bank_account(self, tenant_id: UUID, account_id: UUID) -> AccountInfo:
        acc = await self._accounts.get_by_id(tenant_id, account_id)
        if acc is None:
            raise ValidationError("Payment account not found for this tenant.")
        if not acc.is_active:
            raise ValidationError(f"Account {acc.code} is not active.")
        return acc

    async def _validate_accounts(self, tenant_id: UUID, bill: Bill) -> None:
        for line in bill.lines:
            acc = await self._accounts.get_by_id(tenant_id, line.account_id)
            if acc is None:
                raise ValidationError(f"Account {line.account_id} not found for this tenant.")
            if acc.account_type not in (_EXPENSE_TYPE, _ASSET_TYPE):
                raise ValidationError(
                    f"Account {acc.code} ({acc.name}) is not an expense or asset account."
                )

    def _build_gst_transactions(self, bill: Bill) -> list[GstTransaction]:
        """Aggregate bill lines into one GST transaction per GST code."""
        tenant_id = bill.tenant_id
        if tenant_id is None:
            raise ValidationError("Bill tenant id is required for GST reporting.")
        if bill.issue_date is None:
            raise ValidationError("Bill issue date is required for GST reporting.")

        grouped: dict[UUID, tuple[Decimal, Decimal]] = {}
        for line in bill.lines:
            if line.gst_code_id is None:
                if line.gst_rate > _ZERO or line.gst_amount > _ZERO:
                    raise ValidationError("GST code is required for a bill line with GST.")
                continue

            taxable_amount, gst_amount = grouped.get(
                line.gst_code_id,
                (_ZERO, _ZERO),
            )
            grouped[line.gst_code_id] = (
                taxable_amount + line.line_total,
                gst_amount + line.gst_amount,
            )

        reporting_period = _gst_reporting_period(bill.issue_date)
        return [
            GstTransaction(
                tenant_id=tenant_id,
                source_type=GstSourceType.BILL,
                source_id=bill.id,
                gst_code_id=gst_code_id,
                taxable_amount=taxable_amount,
                gst_amount=gst_amount,
                reporting_period=reporting_period,
                transaction_date=bill.issue_date,
            )
            for gst_code_id, (taxable_amount, gst_amount) in grouped.items()
        ]

    async def _next_bill_number(self, tenant_id: UUID) -> str:
        prefix = "BILL-"
        count = await self._bills.count_with_number_prefix(tenant_id, prefix)
        return f"{prefix}{count + 1:04d}"
