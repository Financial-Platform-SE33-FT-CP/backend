"""AR/AP domain ports (repositories and ledger gateway)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import date
from uuid import UUID

from ar_ap_service.modules.ar_ap.domain.entities import (
    AccountInfo,
    Customer,
    Invoice,
    JournalLineInput,
)


class InvoiceRepository(ABC):
    """Persistence port for invoices and their lines (always tenant-scoped)."""

    @abstractmethod
    async def get_by_id(self, tenant_id: UUID, invoice_id: UUID) -> Invoice | None:
        """Return an invoice with its lines, or ``None`` if not in this tenant."""

    @abstractmethod
    async def list_by_tenant(
        self,
        tenant_id: UUID,
        *,
        status: str | None = None,
        customer_id: UUID | None = None,
        issued_from: date | None = None,
        issued_to: date | None = None,
    ) -> list[Invoice]:
        """List a tenant's invoices, newest first, with optional filters."""

    @abstractmethod
    async def add(self, invoice: Invoice) -> Invoice:
        """Persist a new invoice and its lines."""

    @abstractmethod
    async def update(self, invoice: Invoice) -> Invoice:
        """Persist changes to an existing invoice and replace its lines."""

    @abstractmethod
    async def delete(self, invoice: Invoice) -> None:
        """Remove a draft invoice (only drafts may be deleted)."""

    @abstractmethod
    async def count_with_number_prefix(self, tenant_id: UUID, prefix: str) -> int:
        """Count invoices whose number starts with *prefix* (for numbering)."""


class CustomerRepository(ABC):
    """Persistence port for customers."""

    @abstractmethod
    async def get_by_id(self, tenant_id: UUID, customer_id: UUID) -> Customer | None: ...

    @abstractmethod
    async def list_by_tenant(self, tenant_id: UUID) -> list[Customer]: ...

    @abstractmethod
    async def add(self, customer: Customer) -> Customer: ...


class AccountReader(ABC):
    """Read-only gateway into the Chart of Accounts (owned by coa-service)."""

    @abstractmethod
    async def get_by_id(self, tenant_id: UUID, account_id: UUID) -> AccountInfo | None: ...

    @abstractmethod
    async def get_by_code(self, tenant_id: UUID, code: str) -> AccountInfo | None: ...


class LedgerPoster(ABC):
    """Gateway that posts immutable, balanced journal entries into the ledger.

    Implementations must run inside the caller's transaction so that invoice and
    journal-entry writes commit (or roll back) atomically.
    """

    @abstractmethod
    async def is_period_closed(self, tenant_id: UUID, on_date: date) -> bool:
        """Return True if *on_date* falls inside a closed accounting period."""

    @abstractmethod
    async def post_journal_entry(
        self,
        *,
        tenant_id: UUID,
        entry_date: date,
        reference: str,
        description: str,
        source_id: str,
        created_by: UUID | None,
        lines: Sequence[JournalLineInput],
    ) -> str:
        """Persist a balanced journal entry and return its id."""
