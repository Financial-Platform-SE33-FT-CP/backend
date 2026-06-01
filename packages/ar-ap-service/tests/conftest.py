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

import pytest

from ar_ap_service.config import ArApSettings
from ar_ap_service.modules.ar_ap.application.services import InvoiceService
from ar_ap_service.modules.ar_ap.domain.entities import (
    AccountInfo,
    Customer,
    Invoice,
    JournalLineInput,
)
from ar_ap_service.modules.ar_ap.domain.repository import (
    AccountReader,
    CustomerRepository,
    InvoiceRepository,
    LedgerPoster,
)

TENANT_A = UUID("00000000-0000-0000-0000-0000000000aa")
TENANT_B = UUID("00000000-0000-0000-0000-0000000000bb")

AR_ACCOUNT_ID = UUID("11111111-1111-1111-1111-111111111111")
REVENUE_ACCOUNT_ID = UUID("44444444-4444-4444-4444-444444444444")
REVENUE_ACCOUNT_2_ID = UUID("44444444-4444-4444-4444-444444444445")
GST_ACCOUNT_ID = UUID("22222222-2222-2222-2222-222222222222")
EXPENSE_ACCOUNT_ID = UUID("55555555-5555-5555-5555-555555555555")


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
                "created_by": created_by,
                "lines": line_list,
                "total_debit": total_debit,
                "total_credit": total_credit,
            }
        )
        return entry_id


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
        jwt_secret="test-secret",
    )


@pytest.fixture
def service(
    invoices: FakeInvoiceRepository,
    customers: FakeCustomerRepository,
    accounts: FakeAccountReader,
    ledger: FakeLedgerPoster,
    settings: ArApSettings,
) -> InvoiceService:
    return InvoiceService(
        invoices=invoices,
        customers=customers,
        accounts=accounts,
        ledger=ledger,
        settings=settings,
    )


@pytest.fixture
def customer_a(customers: FakeCustomerRepository) -> Customer:
    return next(c for c in customers._store.values() if c.tenant_id == TENANT_A)


@pytest.fixture
def customer_b(customers: FakeCustomerRepository) -> Customer:
    return next(c for c in customers._store.values() if c.tenant_id == TENANT_B)
