"""Test configuration and in-memory fakes for AR/AP Service.

Business logic for US-8 lives in ``InvoiceService`` behind repository/poster
ports, so we exercise it with deterministic in-memory fakes instead of a real
database. This mirrors the repo's existing mock-driven AR/AP tests and keeps the
suite fast and dialect-independent.
"""

from __future__ import annotations

import copy
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4
from collections.abc import Sequence

import pytest

from ar_ap_service.config import ArApSettings
from ar_ap_service.modules.ar_ap.application.services import (
    BillPaymentService,
    BillService,
    CreditNoteService,
    GstService,
    InvoiceService,
    PaymentService,
)
from ar_ap_service.modules.ar_ap.domain.entities import (
    AccountInfo,
    Bill,
    BillPayment,
    CreditNote,
    Customer,
    GstCode,
    GstKind,
    GstTransaction,
    Invoice,
    JournalLineInput,
    Payment,
    Vendor,
)
from ar_ap_service.modules.ar_ap.domain.repository import (
    AccountReader,
    BillPaymentRepository,
    BillRepository,
    CreditNoteRepository,
    CustomerRepository,
    GstRepository,
    InvoiceRepository,
    LedgerPoster,
    PaymentRepository,
    VendorRepository,
)

TENANT_A = UUID("00000000-0000-0000-0000-0000000000aa")
TENANT_B = UUID("00000000-0000-0000-0000-0000000000bb")

AR_ACCOUNT_ID = UUID("11111111-1111-1111-1111-111111111111")
AP_ACCOUNT_ID = UUID("66666666-6666-6666-6666-666666666666")
REVENUE_ACCOUNT_ID = UUID("44444444-4444-4444-4444-444444444444")
REVENUE_ACCOUNT_2_ID = UUID("44444444-4444-4444-4444-444444444445")
GST_ACCOUNT_ID = UUID("22222222-2222-2222-2222-222222222222")
GST_INPUT_ACCOUNT_ID = UUID("77777777-7777-7777-7777-777777777777")
GST_OUTPUT_CODE_ID = UUID("88888888-8888-8888-8888-888888888881")
GST_INPUT_CODE_ID = UUID("88888888-8888-8888-8888-888888888882")
GST_ZERO_RATED_CODE_ID = UUID("88888888-8888-8888-8888-888888888883")
GST_EXEMPT_CODE_ID = UUID("88888888-8888-8888-8888-888888888884")
EXPENSE_ACCOUNT_ID = UUID("55555555-5555-5555-5555-555555555555")
BANK_ACCOUNT_ID = UUID("33333333-3333-3333-3333-333333333333")


class FakeInvoiceRepository(InvoiceRepository):
    def __init__(self) -> None:
        self._store: dict[UUID, Invoice] = {}

    async def get_by_id(self, tenant_id: UUID, invoice_id: UUID) -> Invoice | None:
        invoice = self._store.get(invoice_id)
        if invoice is None or invoice.tenant_id != tenant_id:
            return None
        return copy.deepcopy(invoice)

    async def list_by_tenant(
        self,
        tenant_id: UUID,
        *,
        status: str | None = None,
        customer_id: UUID | None = None,
        issued_from: date | None = None,
        issued_to: date | None = None,
    ) -> list[Invoice]:
        result = []
        for inv in self._store.values():
            if inv.tenant_id != tenant_id:
                continue
            if status is not None and inv.status.value != status:
                continue
            if customer_id is not None and inv.customer_id != customer_id:
                continue
            if issued_from is not None and (inv.issue_date is None or inv.issue_date < issued_from):
                continue
            if issued_to is not None and (inv.issue_date is None or inv.issue_date > issued_to):
                continue
            result.append(copy.deepcopy(inv))
        return result

    async def add(self, invoice: Invoice) -> Invoice:
        self._store[invoice.id] = copy.deepcopy(invoice)
        return copy.deepcopy(invoice)

    async def update(self, invoice: Invoice) -> Invoice:
        self._store[invoice.id] = copy.deepcopy(invoice)
        return copy.deepcopy(invoice)

    async def delete(self, invoice: Invoice) -> None:
        self._store.pop(invoice.id, None)

    async def count_with_number_prefix(self, tenant_id: UUID, prefix: str) -> int:
        return sum(
            1
            for inv in self._store.values()
            if inv.tenant_id == tenant_id and inv.invoice_number.startswith(prefix)
        )


class FakeCustomerRepository(CustomerRepository):
    def __init__(self) -> None:
        self._store: dict[UUID, Customer] = {}

    def seed(self, customer: Customer) -> Customer:
        self._store[customer.id] = customer
        return customer

    async def get_by_id(self, tenant_id: UUID, customer_id: UUID) -> Customer | None:
        customer = self._store.get(customer_id)
        if customer is None or customer.tenant_id != tenant_id:
            return None
        return customer

    async def list_by_tenant(self, tenant_id: UUID) -> list[Customer]:
        return [c for c in self._store.values() if c.tenant_id == tenant_id]

    async def add(self, customer: Customer) -> Customer:
        self._store[customer.id] = customer
        return customer


class FakeAccountReader(AccountReader):
    def __init__(self) -> None:
        self._by_id: dict[tuple[UUID, UUID], AccountInfo] = {}
        self._by_code: dict[tuple[UUID, str], AccountInfo] = {}

    def seed(self, tenant_id: UUID, account: AccountInfo) -> None:
        self._by_id[(tenant_id, account.id)] = account
        self._by_code[(tenant_id, account.code)] = account

    async def get_by_id(self, tenant_id: UUID, account_id: UUID) -> AccountInfo | None:
        return self._by_id.get((tenant_id, account_id))

    async def get_by_code(self, tenant_id: UUID, code: str) -> AccountInfo | None:
        return self._by_code.get((tenant_id, code))


class FakeLedgerPoster(LedgerPoster):
    def __init__(self) -> None:
        self.posted: list[dict[str, object]] = []
        self.closed_dates: set[date] = set()
        self.fail_with: Exception | None = None

    async def is_period_closed(self, tenant_id: UUID, on_date: date) -> bool:
        return on_date in self.closed_dates

    async def post_journal_entry(
        self,
        *,
        tenant_id: UUID,
        entry_date: date,
        reference: str,
        description: str,
        source_id: str,
        created_by: UUID | None,
        lines,
        source_type: str = "invoice",
        is_reversal: bool = False,
        reversed_entry_id: str | None = None,
    ) -> str:
        if self.fail_with is not None:
            raise self.fail_with
        from accounting_shared.exceptions import ConflictError, ValidationError

        line_list: list[JournalLineInput] = list(lines)
        total_debit = sum((line_item.debit_amount for line_item in line_list), Decimal("0.00"))
        total_credit = sum((line_item.credit_amount for line_item in line_list), Decimal("0.00"))
        if total_debit != total_credit:
            raise ValidationError("Unbalanced journal entry.")
        if await self.is_period_closed(tenant_id, entry_date):
            raise ConflictError(f"{entry_date} is in a closed accounting period.")

        entry_id = str(uuid4())
        self.posted.append(
            {
                "id": entry_id,
                "tenant_id": tenant_id,
                "entry_date": entry_date,
                "reference": reference,
                "source_id": source_id,
                "source_type": source_type,
                "created_by": created_by,
                "lines": line_list,
                "total_debit": total_debit,
                "total_credit": total_credit,
                "is_reversal": is_reversal,
                "reversed_entry_id": reversed_entry_id,
            }
        )
        return entry_id
    

class FakeGstRepository(GstRepository):
    """In-memory GST repository used by service tests."""

    def __init__(self) -> None:
        self._codes: dict[UUID, GstCode] = {}
        self._transactions: list[GstTransaction] = []

    async def get_code_by_id(
        self,
        tenant_id: UUID,
        gst_code_id: UUID,
    ) -> GstCode | None:
        code = self._codes.get(gst_code_id)

        if code is None or code.tenant_id != tenant_id:
            return None

        return copy.deepcopy(code)

    async def list_codes(
        self,
        tenant_id: UUID,
        *,
        active_only: bool = True,
    ) -> list[GstCode]:
        codes = [
            code
            for code in self._codes.values()
            if code.tenant_id == tenant_id
            and (not active_only or code.is_active)
        ]

        return [
            copy.deepcopy(code)
            for code in sorted(codes, key=lambda item: item.code)
        ]
    
    async def add_codes(
        self,
        codes: Sequence[GstCode],
    ) -> list[GstCode]:
        saved: list[GstCode] = []

        for code in codes:
            copied = copy.deepcopy(code)
            self._codes[copied.id] = copied
            saved.append(copied)

        return copy.deepcopy(saved)

    async def add_transactions(
        self,
        transactions: Sequence[GstTransaction],
    ) -> list[GstTransaction]:
        saved = [
            copy.deepcopy(transaction)
            for transaction in transactions
        ]
        self._transactions.extend(saved)
        return copy.deepcopy(saved)

    async def list_transactions_by_period(
        self,
        tenant_id: UUID,
        reporting_period: str,
    ) -> list[GstTransaction]:
        return [
            copy.deepcopy(transaction)
            for transaction in self._transactions
            if transaction.tenant_id == tenant_id
            and transaction.reporting_period == reporting_period
        ]    


@pytest.fixture
def invoices() -> FakeInvoiceRepository:
    return FakeInvoiceRepository()


@pytest.fixture
def customers() -> FakeCustomerRepository:
    repo = FakeCustomerRepository()
    repo.seed(Customer(id=uuid4(), tenant_id=TENANT_A, name="Acme Pte Ltd"))
    repo.seed(Customer(id=uuid4(), tenant_id=TENANT_B, name="Globex Pte Ltd"))
    return repo


@pytest.fixture
def accounts() -> FakeAccountReader:
    reader = FakeAccountReader()
    for tenant in (TENANT_A, TENANT_B):
        reader.seed(
            tenant,
            AccountInfo(AR_ACCOUNT_ID, "1100", "Accounts Receivable", "asset", True),
        )
        reader.seed(
            tenant,
            AccountInfo(GST_ACCOUNT_ID, "2100", "GST Output Tax", "liability", True),
        )
        reader.seed(
            tenant,
            AccountInfo(REVENUE_ACCOUNT_ID, "4000", "Sales Revenue", "revenue", True),
        )
        reader.seed(
            tenant,
            AccountInfo(REVENUE_ACCOUNT_2_ID, "4100", "Service Revenue", "revenue", True),
        )
        reader.seed(
            tenant,
            AccountInfo(EXPENSE_ACCOUNT_ID, "6000", "Rent Expense", "expense", True),
        )
        reader.seed(
            tenant,
            AccountInfo(BANK_ACCOUNT_ID, "1000", "Cash at Bank", "asset", True),
        )
        reader.seed(
            tenant,
            AccountInfo(AP_ACCOUNT_ID, "2000", "Accounts Payable", "liability", True),
        )
        reader.seed(
            tenant,
            AccountInfo(GST_INPUT_ACCOUNT_ID, "1200", "GST Input Tax", "asset", True),
        )
    return reader


@pytest.fixture
def ledger() -> FakeLedgerPoster:
    return FakeLedgerPoster()


@pytest.fixture
def settings() -> ArApSettings:
    return ArApSettings(
        tenant_internal_api_token="test-token",
        ar_control_account_code="1100",
        gst_output_account_code="2100",
        ap_control_account_code="2000",
        gst_input_account_code="1200",
        jwt_secret="test-secret",
    )


@pytest.fixture
def service(
    invoices: FakeInvoiceRepository,
    customers: FakeCustomerRepository,
    accounts: FakeAccountReader,
    gst: FakeGstRepository,
    ledger: FakeLedgerPoster,
    settings: ArApSettings,
) -> InvoiceService:
    return InvoiceService(
        invoices=invoices,
        customers=customers,
        accounts=accounts,
        gst=gst,
        ledger=ledger,
        settings=settings,
    )


@pytest.fixture
def customer_a(customers: FakeCustomerRepository) -> Customer:
    return next(c for c in customers._store.values() if c.tenant_id == TENANT_A)


@pytest.fixture
def customer_b(customers: FakeCustomerRepository) -> Customer:
    return next(c for c in customers._store.values() if c.tenant_id == TENANT_B)


class FakePaymentRepository(PaymentRepository):
    def __init__(self) -> None:
        self._store: dict[UUID, Payment] = {}

    async def add(self, payment: Payment) -> Payment:
        self._store[payment.id] = copy.deepcopy(payment)
        return copy.deepcopy(payment)

    async def get_by_id(self, tenant_id: UUID, payment_id: UUID) -> Payment | None:
        payment = self._store.get(payment_id)
        if payment is None or payment.tenant_id != tenant_id:
            return None
        return copy.deepcopy(payment)

    async def list_by_invoice(self, tenant_id: UUID, invoice_id: UUID) -> list[Payment]:
        return [
            copy.deepcopy(p)
            for p in sorted(self._store.values(), key=lambda p: p.created_at)
            if p.tenant_id == tenant_id and p.invoice_id == invoice_id
        ]

    async def list_by_tenant(
        self,
        tenant_id: UUID,
        *,
        invoice_id: UUID | None = None,
        customer_id: UUID | None = None,
        payment_method: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[Payment]:
        result = []
        for p in sorted(self._store.values(), key=lambda p: p.created_at, reverse=True):
            if p.tenant_id != tenant_id:
                continue
            if invoice_id is not None and p.invoice_id != invoice_id:
                continue
            if customer_id is not None and p.customer_id != customer_id:
                continue
            if payment_method is not None and p.payment_method.value != payment_method:
                continue
            if date_from is not None and (p.payment_date is None or p.payment_date < date_from):
                continue
            if date_to is not None and (p.payment_date is None or p.payment_date > date_to):
                continue
            result.append(copy.deepcopy(p))
        return result

    async def sum_paid_for_invoice(self, tenant_id: UUID, invoice_id: UUID) -> Decimal:
        total = Decimal("0.00")
        for p in self._store.values():
            if p.tenant_id == tenant_id and p.invoice_id == invoice_id:
                total += p.amount
        return total

    async def get_by_idempotency_key(self, tenant_id: UUID, key: str) -> Payment | None:
        for p in self._store.values():
            if p.tenant_id == tenant_id and p.idempotency_key == key:
                return copy.deepcopy(p)
        return None


@pytest.fixture
def payments() -> FakePaymentRepository:
    return FakePaymentRepository()


@pytest.fixture
def payment_service(
    payments: FakePaymentRepository,
    invoices: FakeInvoiceRepository,
    customers: FakeCustomerRepository,
    accounts: FakeAccountReader,
    ledger: FakeLedgerPoster,
    settings: ArApSettings,
) -> PaymentService:
    return PaymentService(
        payments=payments,
        invoices=invoices,
        customers=customers,
        accounts=accounts,
        ledger=ledger,
        settings=settings,
    )


class FakeCreditNoteRepository(CreditNoteRepository):
    def __init__(self) -> None:
        self._store: dict[UUID, CreditNote] = {}

    async def add(self, credit_note: CreditNote) -> CreditNote:
        self._store[credit_note.id] = copy.deepcopy(credit_note)
        return copy.deepcopy(credit_note)

    async def get_by_id(self, tenant_id: UUID, credit_note_id: UUID) -> CreditNote | None:
        credit_note = self._store.get(credit_note_id)
        if credit_note is None or credit_note.tenant_id != tenant_id:
            return None
        return copy.deepcopy(credit_note)

    async def list_by_invoice(self, tenant_id: UUID, invoice_id: UUID) -> list[CreditNote]:
        return [
            copy.deepcopy(cn)
            for cn in sorted(self._store.values(), key=lambda cn: cn.created_at)
            if cn.tenant_id == tenant_id and cn.invoice_id == invoice_id
        ]

    async def list_by_tenant(
        self,
        tenant_id: UUID,
        *,
        invoice_id: UUID | None = None,
        customer_id: UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[CreditNote]:
        result = []
        for cn in sorted(self._store.values(), key=lambda cn: cn.created_at, reverse=True):
            if cn.tenant_id != tenant_id:
                continue
            if invoice_id is not None and cn.invoice_id != invoice_id:
                continue
            if customer_id is not None and cn.customer_id != customer_id:
                continue
            if date_from is not None and (cn.issue_date is None or cn.issue_date < date_from):
                continue
            if date_to is not None and (cn.issue_date is None or cn.issue_date > date_to):
                continue
            result.append(copy.deepcopy(cn))
        return result

    async def sum_credited_for_invoice(self, tenant_id: UUID, invoice_id: UUID) -> Decimal:
        total = Decimal("0.00")
        for cn in self._store.values():
            if cn.tenant_id == tenant_id and cn.invoice_id == invoice_id:
                total += cn.total
        return total

    async def count_with_number_prefix(self, tenant_id: UUID, prefix: str) -> int:
        return sum(
            1
            for cn in self._store.values()
            if cn.tenant_id == tenant_id and cn.credit_note_number.startswith(prefix)
        )

    async def get_by_idempotency_key(self, tenant_id: UUID, key: str) -> CreditNote | None:
        for cn in self._store.values():
            if cn.tenant_id == tenant_id and cn.idempotency_key == key:
                return copy.deepcopy(cn)
        return None


@pytest.fixture
def credit_notes() -> FakeCreditNoteRepository:
    return FakeCreditNoteRepository()


class FakeBillRepository(BillRepository):
    def __init__(self) -> None:
        self._store: dict[UUID, Bill] = {}

    async def get_by_id(self, tenant_id: UUID, bill_id: UUID) -> Bill | None:
        bill = self._store.get(bill_id)
        if bill is None or bill.tenant_id != tenant_id:
            return None
        return copy.deepcopy(bill)

    async def list_by_tenant(
        self,
        tenant_id: UUID,
        *,
        status: str | None = None,
        vendor_id: UUID | None = None,
        issued_from: date | None = None,
        issued_to: date | None = None,
    ) -> list[Bill]:
        result = []
        for bill in self._store.values():
            if bill.tenant_id != tenant_id:
                continue
            if status is not None and bill.status.value != status:
                continue
            if vendor_id is not None and bill.vendor_id != vendor_id:
                continue
            if issued_from is not None and (bill.issue_date is None or bill.issue_date < issued_from):
                continue
            if issued_to is not None and (bill.issue_date is None or bill.issue_date > issued_to):
                continue
            result.append(copy.deepcopy(bill))
        return result

    async def add(self, bill: Bill) -> Bill:
        self._store[bill.id] = copy.deepcopy(bill)
        return copy.deepcopy(bill)

    async def update(self, bill: Bill) -> Bill:
        self._store[bill.id] = copy.deepcopy(bill)
        return copy.deepcopy(bill)

    async def delete(self, bill: Bill) -> None:
        self._store.pop(bill.id, None)

    async def count_with_number_prefix(self, tenant_id: UUID, prefix: str) -> int:
        return sum(
            1
            for bill in self._store.values()
            if bill.tenant_id == tenant_id and bill.bill_number.startswith(prefix)
        )


class FakeVendorRepository(VendorRepository):
    def __init__(self) -> None:
        self._store: dict[UUID, Vendor] = {}

    def seed(self, vendor: Vendor) -> Vendor:
        self._store[vendor.id] = vendor
        return vendor

    async def get_by_id(self, tenant_id: UUID, vendor_id: UUID) -> Vendor | None:
        vendor = self._store.get(vendor_id)
        if vendor is None or vendor.tenant_id != tenant_id:
            return None
        return vendor

    async def list_by_tenant(self, tenant_id: UUID) -> list[Vendor]:
        return [v for v in self._store.values() if v.tenant_id == tenant_id]

    async def add(self, vendor: Vendor) -> Vendor:
        self._store[vendor.id] = vendor
        return vendor


class FakeBillPaymentRepository(BillPaymentRepository):
    def __init__(self) -> None:
        self._store: dict[UUID, BillPayment] = {}

    async def add(self, payment: BillPayment) -> BillPayment:
        self._store[payment.id] = copy.deepcopy(payment)
        return copy.deepcopy(payment)

    async def get_by_id(self, tenant_id: UUID, payment_id: UUID) -> BillPayment | None:
        payment = self._store.get(payment_id)
        if payment is None or payment.tenant_id != tenant_id:
            return None
        return copy.deepcopy(payment)

    async def list_by_bill(self, tenant_id: UUID, bill_id: UUID) -> list[BillPayment]:
        return [
            copy.deepcopy(p)
            for p in sorted(self._store.values(), key=lambda p: p.created_at)
            if p.tenant_id == tenant_id and p.bill_id == bill_id
        ]

    async def list_by_tenant(
        self,
        tenant_id: UUID,
        *,
        bill_id: UUID | None = None,
        vendor_id: UUID | None = None,
        payment_method: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[BillPayment]:
        result = []
        for p in sorted(self._store.values(), key=lambda p: p.created_at, reverse=True):
            if p.tenant_id != tenant_id:
                continue
            if bill_id is not None and p.bill_id != bill_id:
                continue
            if vendor_id is not None and p.vendor_id != vendor_id:
                continue
            if payment_method is not None and p.payment_method.value != payment_method:
                continue
            if date_from is not None and (p.payment_date is None or p.payment_date < date_from):
                continue
            if date_to is not None and (p.payment_date is None or p.payment_date > date_to):
                continue
            result.append(copy.deepcopy(p))
        return result

    async def sum_paid_for_bill(self, tenant_id: UUID, bill_id: UUID) -> Decimal:
        total = Decimal("0.00")
        for p in self._store.values():
            if p.tenant_id == tenant_id and p.bill_id == bill_id:
                total += p.amount
        return total

    async def get_by_idempotency_key(self, tenant_id: UUID, key: str) -> BillPayment | None:
        for p in self._store.values():
            if p.tenant_id == tenant_id and p.idempotency_key == key:
                return copy.deepcopy(p)
        return None


@pytest.fixture
def bills() -> FakeBillRepository:
    return FakeBillRepository()


@pytest.fixture
def vendors() -> FakeVendorRepository:
    repo = FakeVendorRepository()
    repo.seed(Vendor(id=uuid4(), tenant_id=TENANT_A, name="Supplier Co"))
    repo.seed(Vendor(id=uuid4(), tenant_id=TENANT_B, name="Other Vendor"))
    return repo


@pytest.fixture
def bill_payments() -> FakeBillPaymentRepository:
    return FakeBillPaymentRepository()


@pytest.fixture
def bill_service(
    bills: FakeBillRepository,
    vendors: FakeVendorRepository,
    accounts: FakeAccountReader,
    gst: FakeGstRepository,
    ledger: FakeLedgerPoster,
    settings: ArApSettings,
) -> BillService:
    return BillService(
        bills=bills,
        vendors=vendors,
        accounts=accounts,
        gst=gst,
        ledger=ledger,
        settings=settings,
    )


@pytest.fixture
def vendor_a(vendors: FakeVendorRepository) -> Vendor:
    return next(v for v in vendors._store.values() if v.tenant_id == TENANT_A)


@pytest.fixture
def bill_payment_service(
    bill_payments: FakeBillPaymentRepository,
    bills: FakeBillRepository,
    vendors: FakeVendorRepository,
    accounts: FakeAccountReader,
    ledger: FakeLedgerPoster,
    settings: ArApSettings,
) -> BillPaymentService:
    return BillPaymentService(
        bill_payments=bill_payments,
        bills=bills,
        vendors=vendors,
        accounts=accounts,
        ledger=ledger,
        settings=settings,
    )


@pytest.fixture
def credit_note_service(
    credit_notes: FakeCreditNoteRepository,
    invoices: FakeInvoiceRepository,
    customers: FakeCustomerRepository,
    accounts: FakeAccountReader,
    gst: FakeGstRepository,
    ledger: FakeLedgerPoster,
    settings: ArApSettings,
) -> CreditNoteService:
    return CreditNoteService(
        credit_notes=credit_notes,
        invoices=invoices,
        customers=customers,
        accounts=accounts,
        gst=gst,
        ledger=ledger,
        settings=settings,
    )


@pytest.fixture
def gst() -> FakeGstRepository:
    repository = FakeGstRepository()

    codes = [
        GstCode(
            id=GST_OUTPUT_CODE_ID,
            tenant_id=TENANT_A,
            code="SR-OUTPUT",
            rate=Decimal("0.09"),
            gst_kind=GstKind.OUTPUT,
            is_active=True,
        ),
        GstCode(
            id=GST_INPUT_CODE_ID,
            tenant_id=TENANT_A,
            code="SR-INPUT",
            rate=Decimal("0.09"),
            gst_kind=GstKind.INPUT,
            is_active=True,
        ),
        GstCode(
            id=GST_ZERO_RATED_CODE_ID,
            tenant_id=TENANT_A,
            code="ZERO",
            rate=Decimal("0"),
            gst_kind=GstKind.ZERO_RATED,
            is_active=True,
        ),
        GstCode(
            id=GST_EXEMPT_CODE_ID,
            tenant_id=TENANT_A,
            code="EXEMPT",
            rate=Decimal("0"),
            gst_kind=GstKind.EXEMPT,
            is_active=True,
        ),
    ]

    repository._codes = {
        code.id: code
        for code in codes
    }

    return repository