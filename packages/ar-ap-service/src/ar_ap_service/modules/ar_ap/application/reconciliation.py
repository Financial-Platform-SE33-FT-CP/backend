"""Bank statement upload and reconciliation services (US-13/US-14).

US-13: Upload Bank Statement (CSV)
  - Parses CSV using bank_statement parser
  - Deduplicates via checksum hash
  - Stores as BankTransaction entities

US-14: Reconcile Bank Transactions
  - Lists unmatched transactions
  - Suggests possible matches against invoices/payments
  - Confirms a match and posts the balancing journal entry
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from accounting_shared.exceptions import NotFoundError, ValidationError

from ar_ap_service.config import ArApSettings
from ar_ap_service.modules.ar_ap.application.bank_statement import (
    ParsedTransaction,
    parse_bank_statement_csv,
)
from ar_ap_service.modules.ar_ap.domain.entities import (
    BankTransaction,
    InvoiceStatus,
    JournalLineInput,
    Payment,
    PaymentMethod,
    ReconciliationSuggestion,
)
from ar_ap_service.modules.ar_ap.domain.repository import (
    AccountReader,
    BankTransactionRepository,
    BillRepository,
    InvoiceRepository,
    LedgerPoster,
    PaymentRepository,
)

_ZERO = Decimal("0.00")

class ReconciliationService:
    """Handles manual bank transaction reconciliation (US-14)."""

    def __init__(
        self,
        bank_txn_repo: BankTransactionRepository,
        invoice_repo: InvoiceRepository,
        payment_repo: PaymentRepository,
        ledger_poster: LedgerPoster,
        bill_repo: BillRepository | None = None,
        accounts: AccountReader | None = None,
        settings: ArApSettings | None = None,
    ) -> None:
        self._bank_txn_repo = bank_txn_repo
        self._invoice_repo = invoice_repo
        self._payment_repo = payment_repo
        self._ledger_poster = ledger_poster
        self._bill_repo = bill_repo
        self._accounts = accounts
        self._settings = settings

    async def list_unmatched(
        self,
        tenant_id: UUID,
        *,
        bank_account_id: UUID | None = None,
    ) -> list[BankTransaction]:
        """List unmatched bank transactions ready for reconciliation."""
        return await self._bank_txn_repo.list_unmatched(
            tenant_id,
            bank_account_id=bank_account_id,
        )

    async def list_matched(
        self,
        tenant_id: UUID,
        *,
        bank_account_id: UUID | None = None,
    ) -> list[BankTransaction]:
        """List previously reconciled bank transactions."""
        return await self._bank_txn_repo.list_matched(
            tenant_id,
            bank_account_id=bank_account_id,
        )

    async def suggest_matches(
        self,
        tenant_id: UUID,
        transaction_id: UUID,
    ) -> list[ReconciliationSuggestion]:
        """Find possible matches for a single unmatched bank transaction.

        For MVP, suggests:
        - Invoices whose total matches the absolute transaction amount
        - Payments whose amount matches the transaction amount
        """
        txn = await self._bank_txn_repo.get_by_id(tenant_id, transaction_id)
        if txn is None:
            raise NotFoundError("Bank transaction not found")
        if txn.matched:
            raise ValidationError("Bank transaction is already reconciled")

        abs_amount = abs(txn.amount)
        suggestions: list[ReconciliationSuggestion] = []

        # Match against invoices (all transaction amounts, not just positive)
        invoices = await self._invoice_repo.list_by_tenant(
            tenant_id,
            status=InvoiceStatus.ISSUED,
        )
        for inv in invoices:
            diff = abs_amount - inv.total
            conf = "exact" if diff == _ZERO else "partial"
            suggestions.append(ReconciliationSuggestion(
                bank_transaction_id=transaction_id,
                match_type="invoice",
                match_id=inv.id,
                match_label=inv.invoice_number or str(inv.id)[:8],
                match_amount=inv.total,
                difference=abs(diff),
                confidence=conf,
            ))

        # Also match against known payments
        payments = await self._payment_repo.list_by_tenant(tenant_id)
        for pmt in payments:
            diff = abs_amount - pmt.amount
            conf = "exact" if diff == _ZERO else "partial"
            suggestions.append(ReconciliationSuggestion(
                bank_transaction_id=transaction_id,
                match_type="payment",
                match_id=pmt.id,
                match_label=f"PAY-{str(pmt.id)[:8]}",
                match_amount=pmt.amount,
                difference=abs(diff),
                confidence=conf,
            ))

        # Also match against open bills (AP)
        if self._bill_repo is not None:
            all_bills = await self._bill_repo.list_by_tenant(tenant_id)
            for bill in all_bills:
                if bill.status.value != "draft":
                    diff = abs_amount - bill.total
                    conf = "exact" if diff == _ZERO else "partial"
                    suggestions.append(ReconciliationSuggestion(
                        bank_transaction_id=transaction_id,
                        match_type="bill",
                        match_id=bill.id,
                        match_label=bill.bill_number or str(bill.id)[:8],
                        match_amount=bill.total,
                        difference=abs(diff),
                        confidence=conf,
                    ))
        # Sort by difference ascending (best match first)
        suggestions.sort(key=lambda s: s.difference)
        return suggestions

    async def confirm_match(
        self,
        tenant_id: UUID,
        user_id: UUID | None,
        command: ReconcileTransactionCommand,
    ) -> BankTransaction:
        """Confirm a match between a bank transaction and an entity.

        Posts a journal entry:
          Dr <bank account>       (for deposits)
          Cr <counterparty>       (AR account for invoice payments)
        Or the reverse for withdrawals.

        Returns the updated BankTransaction with matched=True and
        journal_entry_id set.
        """
        txn = await self._bank_txn_repo.get_by_id(tenant_id, command.transaction_id)
        if txn is None:
            raise NotFoundError("Bank transaction not found")
        if txn.matched:
            raise ValidationError("Bank transaction is already reconciled")

        # Determine the counterparty account for the journal entry
        counterparty_id: str | None = None
        if command.match_type == "invoice" and self._accounts is not None and self._settings is not None:
            ar_account = await self._accounts.get_by_code(tenant_id, self._settings.ar_control_account_code)
            if ar_account is not None:
                counterparty_id = str(ar_account.id)
            else:
                raise ValidationError(
                    f"AR control account with code '{self._settings.ar_control_account_code}' "
                    f"not found for this tenant. Cannot post reconciliation journal entry."
                )
        elif command.match_type == "other" and command.match_id is not None:
            counterparty_id = str(command.match_id)
        else:
            counterparty_id = str(command.account_id)

        # Build reference description
        ref_parts = [f"Reconciliation: {txn.description or 'Bank transaction'}"]
        if command.match_type != "other" and command.match_id is not None:
            ref_parts.append(f"matched to {command.match_type} {command.match_id}")

        # Post journal entry
        abs_amount = abs(txn.amount)
        lines: list[JournalLineInput] = []
        bank_account_id_str = str(command.account_id)

        if txn.amount >= _ZERO:
            lines.append(JournalLineInput(
                account_id=bank_account_id_str,
                debit_amount=abs_amount,
                description=txn.description or "Bank deposit",
            ))
            lines.append(JournalLineInput(
                account_id=counterparty_id,
                credit_amount=abs_amount,
                description=f"Matched {command.match_type}",
            ))
        else:
            lines.append(JournalLineInput(
                account_id=bank_account_id_str,
                credit_amount=abs_amount,
                description=txn.description or "Bank withdrawal",
            ))
            lines.append(JournalLineInput(
                account_id=counterparty_id,
                debit_amount=abs_amount,
                description=f"Matched {command.match_type}",
            ))

        entry_id = await self._ledger_poster.post_journal_entry(
            tenant_id=tenant_id,
            entry_date=txn.transaction_date or date.today(),
            reference=f"RECON-{str(txn.id)[:8]}",
            description="; ".join(ref_parts),
            source_id=str(txn.id),
            created_by=user_id,
            lines=lines,
            source_type="reconciliation",
        )
        await self._bank_txn_repo.update_reconciliation(
            tenant_id,
            txn.id,
            matched=True,
            journal_entry_id=entry_id,
            reconciliation_entity_type=command.match_type,
            reconciliation_entity_id=command.match_id,
        )

        # When matching against an invoice, also record a payment and update invoice status
        # so the invoice no longer appears as a matchable candidate.
        if command.match_type == "invoice" and command.match_id is not None and txn.amount > _ZERO:
            invoice = await self._invoice_repo.get_by_id(tenant_id, command.match_id)
            if invoice is not None and invoice.status in (InvoiceStatus.ISSUED, InvoiceStatus.PARTIAL, InvoiceStatus.OVERDUE):
                already_paid = await self._payment_repo.sum_paid_for_invoice(tenant_id, command.match_id)
                outstanding = invoice.total - already_paid
                recon_amount = abs(txn.amount)
                if recon_amount > _ZERO and outstanding > _ZERO:
                    pmt_amount = min(recon_amount, outstanding)
                    payment = Payment(
                        id=uuid4(),
                        tenant_id=tenant_id,
                        invoice_id=invoice.id,
                        customer_id=invoice.customer_id,
                        amount=pmt_amount,
                        payment_date=txn.transaction_date or date.today(),
                        payment_method=PaymentMethod.BANK_TRANSFER,
                        reference=f"RECON-{str(txn.id)[:8]}",
                        deposit_account_id=command.account_id,
                        journal_entry_id=entry_id,
                        created_by=user_id,
                    )
                    await self._payment_repo.add(payment)
                    remaining = outstanding - pmt_amount
                    if remaining <= _ZERO:
                        invoice.status = InvoiceStatus.PAID
                    else:
                        invoice.status = InvoiceStatus.PARTIAL
                    invoice.updated_at = datetime.utcnow()
                    await self._invoice_repo.update(invoice)

        updated = await self._bank_txn_repo.get_by_id(tenant_id, txn.id)
        assert updated is not None
        return updated
