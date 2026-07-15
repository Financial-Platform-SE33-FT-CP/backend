"""AR/AP domain ports (repositories and ledger gateway)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from uuid import UUID

from ar_ap_service.modules.ar_ap.domain.entities import (
    AccountInfo,
    BankAccount,
    BankTransaction,
    Bill,
    BillPayment,
    CreditNote,
    Customer,
    GstCode,
    GstTransaction,
    Invoice,
    JournalLineInput,
    Payment,
    Vendor,
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


class PaymentRepository(ABC):
    """Persistence port for customer payments (always tenant-scoped, US-9).

    Payments are immutable financial records: this port intentionally exposes no
    update or delete method.
    """

    @abstractmethod
    async def add(self, payment: Payment) -> Payment:
        """Persist a new posted payment."""

    @abstractmethod
    async def get_by_id(self, tenant_id: UUID, payment_id: UUID) -> Payment | None:
        """Return a payment, or ``None`` if it is not in this tenant."""

    @abstractmethod
    async def list_by_invoice(self, tenant_id: UUID, invoice_id: UUID) -> list[Payment]:
        """List a tenant's payments for one invoice, oldest first."""

    @abstractmethod
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
        """List a tenant's payments, newest first, with optional filters."""

    @abstractmethod
    async def sum_paid_for_invoice(self, tenant_id: UUID, invoice_id: UUID) -> Decimal:
        """Return the total amount already posted against an invoice."""

    @abstractmethod
    async def get_by_idempotency_key(self, tenant_id: UUID, key: str) -> Payment | None:
        """Return an existing payment for an idempotency key, if any."""


class CreditNoteRepository(ABC):
    """Persistence port for credit notes and their lines (always tenant-scoped, US-10).

    Credit notes are immutable financial records: this port intentionally exposes
    no update or delete method (no hard deletes of posted financial records).
    """

    @abstractmethod
    async def add(self, credit_note: CreditNote) -> CreditNote:
        """Persist a new posted credit note and its lines."""

    @abstractmethod
    async def get_by_id(self, tenant_id: UUID, credit_note_id: UUID) -> CreditNote | None:
        """Return a credit note with its lines, or ``None`` if not in this tenant."""

    @abstractmethod
    async def list_by_invoice(self, tenant_id: UUID, invoice_id: UUID) -> list[CreditNote]:
        """List a tenant's credit notes for one invoice, oldest first."""

    @abstractmethod
    async def list_by_tenant(
        self,
        tenant_id: UUID,
        *,
        invoice_id: UUID | None = None,
        customer_id: UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[CreditNote]:
        """List a tenant's credit notes, newest first, with optional filters."""

    @abstractmethod
    async def sum_credited_for_invoice(self, tenant_id: UUID, invoice_id: UUID) -> Decimal:
        """Return the total amount already credited against an invoice."""

    @abstractmethod
    async def count_with_number_prefix(self, tenant_id: UUID, prefix: str) -> int:
        """Count credit notes whose number starts with *prefix* (for numbering)."""

    @abstractmethod
    async def get_by_idempotency_key(self, tenant_id: UUID, key: str) -> CreditNote | None:
        """Return an existing credit note for an idempotency key, if any."""


class GstRepository(ABC):
    """Persistence port for tenant GST codes and GST reporting transactions."""

    @abstractmethod
    async def get_code_by_id(
        self,
        tenant_id: UUID,
        gst_code_id: UUID,
    ) -> GstCode | None:
        """Return a tenant-scoped GST code, or ``None`` when it does not exist."""

    @abstractmethod
    async def list_codes(
        self,
        tenant_id: UUID,
        *,
        active_only: bool = True,
    ) -> list[GstCode]:
        """List GST codes belonging to a tenant."""

    @abstractmethod
    async def add_codes(
        self,
        codes: Sequence[GstCode],
    ) -> list[GstCode]:
        """Persist tenant-scoped GST codes and return the saved codes."""

    @abstractmethod
    async def add_transactions(
        self,
        transactions: Sequence[GstTransaction],
    ) -> list[GstTransaction]:
        """Persist GST transactions produced by a posted financial document."""

    @abstractmethod
    async def list_transactions_by_period(
        self,
        tenant_id: UUID,
        reporting_period: str,
    ) -> list[GstTransaction]:
        """Return a tenant's GST transactions for one reporting period."""


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
        source_type: str = "invoice",
        is_reversal: bool = False,
        reversed_entry_id: str | None = None,
    ) -> str:
        """Persist a balanced journal entry and return its id.

        ``source_type`` ties the entry back to its originating document
        ("invoice", "payment", "credit_note", ...) so the ledger can be traced
        per source. ``is_reversal``/``reversed_entry_id`` mark an entry that
        reverses or adjusts another (e.g. a credit note against an invoice's
        journal entry) without ever mutating the original.
        """


class BankAccountRepository(ABC):
    """Persistence port for bank accounts."""

    @abstractmethod
    async def get_by_id(self, tenant_id: UUID, account_id: UUID) -> BankAccount | None: ...

    @abstractmethod
    async def list_by_tenant(self, tenant_id: UUID) -> list[BankAccount]: ...

    @abstractmethod
    async def add(self, account: BankAccount) -> BankAccount: ...


class BankTransactionRepository(ABC):
    """Persistence port for bank transactions (US-13/US-14).

    Bank transactions are immutable after upload — only the ``matched``,
    ``journal_entry_id``, ``reconciliation_entity_type``, and
    ``reconciliation_entity_id`` fields may be updated during reconciliation.
    """

    @abstractmethod
    async def add_many(
        self, tenant_id: UUID, transactions: list[BankTransaction]
    ) -> list[BankTransaction]:
        """Persist a batch of new bank transactions."""

    @abstractmethod
    async def get_by_id(self, tenant_id: UUID, transaction_id: UUID) -> BankTransaction | None:
        """Return a bank transaction, or ``None`` if not in this tenant."""

    @abstractmethod
    async def list_unmatched(
        self,
        tenant_id: UUID,
        *,
        bank_account_id: UUID | None = None,
    ) -> list[BankTransaction]:
        """List a tenant's unmatched bank transactions, newest first."""

    @abstractmethod
    async def list_matched(
        self,
        tenant_id: UUID,
        *,
        bank_account_id: UUID | None = None,
    ) -> list[BankTransaction]:
        """List a tenant's matched/reconciled transactions, newest first."""

    @abstractmethod
    async def list_by_batch(self, tenant_id: UUID, batch_id: UUID) -> list[BankTransaction]:
        """List transactions from a specific upload batch."""

    @abstractmethod
    async def exists_by_hash(self, tenant_id: UUID, checksum_hash: str) -> bool:
        """Return True if a transaction with this hash already exists (duplicate check)."""

    @abstractmethod
    async def update_reconciliation(
        self,
        tenant_id: UUID,
        transaction_id: UUID,
        *,
        matched: bool,
        journal_entry_id: str | None,
        reconciliation_entity_type: str | None = None,
        reconciliation_entity_id: UUID | None = None,
    ) -> None:
        """Update reconciliation status for a bank transaction."""


class BillRepository(ABC):
    @abstractmethod
    async def get_by_id(self, tenant_id: UUID, bill_id: UUID) -> Bill | None: ...

    @abstractmethod
    async def list_by_tenant(
        self,
        tenant_id: UUID,
        *,
        status: str | None = None,
        vendor_id: UUID | None = None,
        issued_from: date | None = None,
        issued_to: date | None = None,
    ) -> list[Bill]: ...

    @abstractmethod
    async def add(self, bill: Bill) -> Bill: ...

    @abstractmethod
    async def update(self, bill: Bill) -> Bill: ...

    @abstractmethod
    async def delete(self, bill: Bill) -> None: ...

    @abstractmethod
    async def count_with_number_prefix(self, tenant_id: UUID, prefix: str) -> int: ...


class VendorRepository(ABC):
    @abstractmethod
    async def get_by_id(self, tenant_id: UUID, vendor_id: UUID) -> Vendor | None: ...

    @abstractmethod
    async def list_by_tenant(self, tenant_id: UUID) -> list[Vendor]: ...

    @abstractmethod
    async def add(self, vendor: Vendor) -> Vendor: ...


class BillPaymentRepository(ABC):
    @abstractmethod
    async def add(self, payment: BillPayment) -> BillPayment: ...

    @abstractmethod
    async def list_by_bill(self, tenant_id: UUID, bill_id: UUID) -> list[BillPayment]: ...

    @abstractmethod
    async def sum_paid_for_bill(self, tenant_id: UUID, bill_id: UUID) -> Decimal: ...

    @abstractmethod
    async def get_by_idempotency_key(self, tenant_id: UUID, key: str) -> BillPayment | None: ...
