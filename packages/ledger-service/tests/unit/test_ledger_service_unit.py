from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from accounting_shared.exceptions import (
    ConflictError,
    NotFoundError,
    ServiceUnavailableError,
    ValidationError,
)
from ledger_service.modules.ledger.application.dto import (
    CreateJournalEntryDTO,
    CreateJournalEntryLineDTO,
)
from ledger_service.modules.ledger.application.services import LedgerService
from ledger_service.modules.ledger.domain.entities import (
    JournalEntry,
    LedgerAccountSnapshot,
    TrialBalanceAccountAggregate,
)
from ledger_service.modules.ledger.domain.repository import (
    AccountingPeriodRepository,
    JournalEntryRepository,
)

TENANT_ID = "00000000-0000-0000-0000-000000000001"
ACCOUNT_A = "10000000-0000-0000-0000-000000000001"
ACCOUNT_B = "20000000-0000-0000-0000-000000000001"

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _balanced_dto(
    debit_account=ACCOUNT_A,
    credit_account=ACCOUNT_B,
    debit_amount="100.00",
    credit_amount="100.00",
    **kwargs,
):
    defaults = {
        "entry_date": date.today(),
        "reference": "JE-001",
        "lines": [
            CreateJournalEntryLineDTO(
                account_id=debit_account, debit_amount=Decimal(debit_amount), credit_amount=Decimal("0"), description="dr"
            ),
            CreateJournalEntryLineDTO(
                account_id=credit_account, debit_amount=Decimal("0"), credit_amount=Decimal(credit_amount), description="cr"
            ),
        ],
    }
    defaults.update(kwargs)
    return CreateJournalEntryDTO(**defaults)


def _snapshot(account_id=ACCOUNT_A):
    return LedgerAccountSnapshot(id=account_id, code="1001", name="Cash", account_type="asset")


def _created_entry(dto):
    """Simulate what the real repo.create returns after persisting."""
    from ledger_service.modules.ledger.domain.entities import JournalEntry as JE
    from ledger_service.modules.ledger.domain.entities import JournalEntryLine

    return JE(
        id="entry-uuid",
        tenant_id=TENANT_ID,
        entry_date=dto.entry_date,
        reference=dto.reference,
        description=dto.description,
        source_type="manual",
        created_by="",
        created_at=datetime.now(),
        lines=[
            JournalEntryLine(
                id="line-1",
                tenant_id=TENANT_ID,
                journal_entry_id="entry-uuid",
                account_id=line.account_id,
                debit_amount=line.debit_amount,
                credit_amount=line.credit_amount,
                description=line.description,
            )
            for line in dto.lines
        ],
    )


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def journal_repo():
    return AsyncMock(spec=JournalEntryRepository)


@pytest.fixture
def period_repo():
    return AsyncMock(spec=AccountingPeriodRepository)


@pytest.fixture
def svc(journal_repo, period_repo):
    return LedgerService(journal_repo, period_repo)


@pytest.fixture
def svc_no_period(journal_repo):
    return LedgerService(journal_repo, None)


# ============================================================================
# create_journal_entry — _validate_lines
# ============================================================================


class TestValidateLines:
    async def test_unbalanced_raises(self, svc, journal_repo, period_repo):
        period_repo.is_date_closed.return_value = False
        journal_repo.get_account_snapshot.return_value = _snapshot()
        dto = _balanced_dto(debit_amount="100.00", credit_amount="50.00")
        with pytest.raises(ValidationError, match="not balanced"):
            await svc.create_journal_entry(dto, TENANT_ID)

    def test_single_line_raises(self):
        # Pydantic enforces min_length=2 on lines — validation happens at the schema boundary
        from pydantic import ValidationError as PydanticValidationError

        with pytest.raises(PydanticValidationError, match="at least 2 items"):
            CreateJournalEntryDTO(
                entry_date=date.today(),
                reference="JE-X",
                lines=[CreateJournalEntryLineDTO(account_id=ACCOUNT_A, debit_amount=Decimal("100"))],
            )

    async def test_both_debit_and_credit_on_same_line_raises(self, svc, journal_repo, period_repo):
        period_repo.is_date_closed.return_value = False
        dto = _balanced_dto()
        dto.lines[0].debit_amount = Decimal("100")
        dto.lines[0].credit_amount = Decimal("50")
        with pytest.raises(ValidationError, match="both debit and credit"):
            await svc.create_journal_entry(dto, TENANT_ID)

    async def test_zero_amount_both_lines_raises(self, svc, journal_repo, period_repo):
        period_repo.is_date_closed.return_value = False
        dto = _balanced_dto(debit_amount="0.00", credit_amount="0.00")
        with pytest.raises(ValidationError, match="must have either a debit or credit amount"):
            await svc.create_journal_entry(dto, TENANT_ID)

    async def test_negative_amount_raises(self, svc, journal_repo, period_repo):
        period_repo.is_date_closed.return_value = False
        dto = _balanced_dto(debit_amount="-100.00")
        with pytest.raises(ValidationError, match="must not be negative"):
            await svc.create_journal_entry(dto, TENANT_ID)

    async def test_zero_amount_single_line_raises(self, svc, journal_repo, period_repo):
        period_repo.is_date_closed.return_value = False
        dto = CreateJournalEntryDTO(
            entry_date=date.today(),
            reference="JE-Z",
            lines=[
                CreateJournalEntryLineDTO(account_id=ACCOUNT_A, debit_amount=Decimal("0"), credit_amount=Decimal("0")),
                CreateJournalEntryLineDTO(account_id=ACCOUNT_B, debit_amount=Decimal("0"), credit_amount=Decimal("0")),
            ],
        )
        with pytest.raises(ValidationError, match="a journal line must have either a debit or credit amount"):
            await svc.create_journal_entry(dto, TENANT_ID)


# ============================================================================
# create_journal_entry — other guards
# ============================================================================


class TestCreateJournalEntryGuards:
    async def test_missing_period_repo_raises(self, svc_no_period, journal_repo):
        dto = _balanced_dto()
        with pytest.raises(ServiceUnavailableError, match="Accounting period repository"):
            await svc_no_period.create_journal_entry(dto, TENANT_ID)

    async def test_invalid_tenant_id_raises(self, svc, journal_repo, period_repo):
        period_repo.is_date_closed.return_value = False
        dto = _balanced_dto()
        with pytest.raises(ValidationError, match="Invalid tenant_id"):
            await svc.create_journal_entry(dto, "not-a-uuid")

    async def test_closed_period_raises(self, svc, journal_repo, period_repo):
        period_repo.is_date_closed.return_value = True
        dto = _balanced_dto()
        with pytest.raises(ConflictError, match="closed accounting period"):
            await svc.create_journal_entry(dto, TENANT_ID)

    async def test_account_not_in_coa_raises(self, svc, journal_repo, period_repo):
        period_repo.is_date_closed.return_value = False
        journal_repo.get_account_snapshot.return_value = None
        dto = _balanced_dto()
        with pytest.raises(ValidationError, match="not found in Chart of Accounts"):
            await svc.create_journal_entry(dto, TENANT_ID)


# ============================================================================
# create_journal_entry — success
# ============================================================================


class TestCreateJournalEntrySuccess:
    async def test_balanced_entry_returns_dto(self, svc, journal_repo, period_repo):
        period_repo.is_date_closed.return_value = False
        journal_repo.get_account_snapshot.return_value = _snapshot()
        journal_repo.create.return_value = _created_entry(_balanced_dto())

        result = await svc.create_journal_entry(_balanced_dto(), TENANT_ID)
        assert result.reference == "JE-001"
        assert len(result.lines) == 2
        journal_repo.create.assert_awaited_once()


# ============================================================================
# get_trial_balance
# ============================================================================


class TestGetTrialBalance:
    async def test_balanced_zero_totals(self, svc, journal_repo):
        journal_repo.get_trial_balance_rows.return_value = []
        result = await svc.get_trial_balance(tenant_id=TENANT_ID, as_of_date=None)
        assert result.accounts == []
        assert result.total_debit_balance == Decimal("0.00")
        assert result.total_credit_balance == Decimal("0.00")
        assert result.is_balanced is True
        assert result.imbalance == Decimal("0.00")

    async def test_single_account_debit_balance(self, svc, journal_repo):
        journal_repo.get_trial_balance_rows.return_value = [
            TrialBalanceAccountAggregate(
                account_id=ACCOUNT_A,
                account_code="1001",
                account_name="Cash",
                account_type="asset",
                total_debit=Decimal("200.00"),
                total_credit=Decimal("50.00"),
            )
        ]
        result = await svc.get_trial_balance(tenant_id=TENANT_ID, as_of_date=None)
        assert len(result.accounts) == 1
        acct = result.accounts[0]
        assert acct.debit_balance == Decimal("150.00")
        assert acct.credit_balance == Decimal("0.00")

    async def test_single_account_credit_balance(self, svc, journal_repo):
        journal_repo.get_trial_balance_rows.return_value = [
            TrialBalanceAccountAggregate(
                account_id=ACCOUNT_A,
                account_code="2001",
                account_name="Revenue",
                account_type="revenue",
                total_debit=Decimal("20.00"),
                total_credit=Decimal("120.00"),
            )
        ]
        result = await svc.get_trial_balance(tenant_id=TENANT_ID, as_of_date=None)
        acct = result.accounts[0]
        assert acct.debit_balance == Decimal("0.00")
        assert acct.credit_balance == Decimal("100.00")

    async def test_passes_as_of_date(self, svc, journal_repo):
        journal_repo.get_trial_balance_rows.return_value = []
        cutoff = date(2026, 3, 31)
        await svc.get_trial_balance(tenant_id=TENANT_ID, as_of_date=cutoff)
        journal_repo.get_trial_balance_rows.assert_awaited_once_with(
            tenant_id=TENANT_ID, as_of_date=cutoff
        )


# ============================================================================
# get_account_transactions
# ============================================================================


class TestGetAccountTransactions:
    async def test_from_date_after_to_date_raises(self, svc):
        with pytest.raises(ValidationError, match="from_date cannot be after to_date"):
            await svc.get_account_transactions(
                tenant_id=TENANT_ID,
                account_id=ACCOUNT_A,
                from_date=date(2026, 6, 1),
                to_date=date(2026, 1, 1),
            )

    async def test_account_not_found_raises(self, svc, journal_repo):
        journal_repo.get_account_snapshot.return_value = None
        with pytest.raises(NotFoundError, match="Account not found"):
            await svc.get_account_transactions(
                tenant_id=TENANT_ID,
                account_id=ACCOUNT_A,
                from_date=None,
                to_date=None,
            )

    async def test_returns_view_with_opening_balance(self, svc, journal_repo):
        journal_repo.get_account_snapshot.return_value = _snapshot(ACCOUNT_A)
        journal_repo.get_account_balance_before.return_value = Decimal("50.00")
        journal_repo.list_account_transactions.return_value = []

        result = await svc.get_account_transactions(
            tenant_id=TENANT_ID,
            account_id=ACCOUNT_A,
            from_date=date(2026, 1, 1),
            to_date=None,
        )
        assert result.opening_balance == Decimal("50.00")
        assert result.closing_balance == Decimal("50.00")
        journal_repo.get_account_balance_before.assert_awaited_once()

    async def test_no_opening_balance_when_from_date_is_none(self, svc, journal_repo):
        journal_repo.get_account_snapshot.return_value = _snapshot(ACCOUNT_A)
        journal_repo.list_account_transactions.return_value = []

        result = await svc.get_account_transactions(
            tenant_id=TENANT_ID,
            account_id=ACCOUNT_A,
            from_date=None,
            to_date=None,
        )
        assert result.opening_balance == Decimal("0.00")
        journal_repo.get_account_balance_before.assert_not_called()
