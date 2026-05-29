from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from accounting_shared.exceptions import NotFoundError, ValidationError
from coa_service.modules.coa.infrastructure.models import AccountModel, AccountType
from ledger_service.modules.ledger.application.services import LedgerService
from ledger_service.modules.ledger.infrastructure.repository import SqlAlchemyJournalEntryRepository


def _now_utc() -> datetime:
    return datetime.now(UTC)


async def _create_account(
    session,
    *,
    tenant_id: uuid.UUID,
    account_id: uuid.UUID,
    code: str,
    name: str,
    account_type: AccountType,
) -> None:
    now = _now_utc()
    session.add(
        AccountModel(
            id=account_id,
            tenant_id=tenant_id,
            code=code,
            name=name,
            account_type=account_type,
            parent_id=None,
            is_active=True,
            is_system_default=False,
            created_at=now,
            updated_at=now,
        )
    )
    await session.flush()


@pytest.mark.asyncio
async def test_account_transactions_compute_running_balance_with_opening(session) -> None:
    tenant_id = uuid.uuid4()
    cash_id = uuid.uuid4()
    equity_id = uuid.uuid4()

    await _create_account(
        session,
        tenant_id=tenant_id,
        account_id=cash_id,
        code="1000",
        name="Cash",
        account_type=AccountType.ASSET,
    )
    await _create_account(
        session,
        tenant_id=tenant_id,
        account_id=equity_id,
        code="3200",
        name="Opening Equity",
        account_type=AccountType.EQUITY,
    )

    repo = SqlAlchemyJournalEntryRepository(session)
    service = LedgerService(repo)

    await repo.create_opening_entry(
        tenant_id=str(tenant_id),
        entry_date=date(2026, 1, 1),
        reference="JE-001",
        description="Seed",
        source_type="manual",
        created_by=None,
        lines=[
            {
                "account_id": str(cash_id),
                "debit_amount": Decimal("100.00"),
                "credit_amount": Decimal("0.00"),
            },
            {
                "account_id": str(equity_id),
                "debit_amount": Decimal("0.00"),
                "credit_amount": Decimal("100.00"),
            },
        ],
    )
    await repo.create_opening_entry(
        tenant_id=str(tenant_id),
        entry_date=date(2026, 1, 2),
        reference="JE-002",
        description="Payment",
        source_type="manual",
        created_by=None,
        lines=[
            {
                "account_id": str(cash_id),
                "debit_amount": Decimal("0.00"),
                "credit_amount": Decimal("40.00"),
            },
            {
                "account_id": str(equity_id),
                "debit_amount": Decimal("40.00"),
                "credit_amount": Decimal("0.00"),
            },
        ],
    )
    await repo.create_opening_entry(
        tenant_id=str(tenant_id),
        entry_date=date(2026, 1, 3),
        reference="JE-003",
        description="Top up",
        source_type="manual",
        created_by=None,
        lines=[
            {
                "account_id": str(cash_id),
                "debit_amount": Decimal("25.00"),
                "credit_amount": Decimal("0.00"),
            },
            {
                "account_id": str(equity_id),
                "debit_amount": Decimal("0.00"),
                "credit_amount": Decimal("25.00"),
            },
        ],
    )

    ledger_view = await service.get_account_transactions(
        tenant_id=str(tenant_id),
        account_id=str(cash_id),
        from_date=date(2026, 1, 2),
        to_date=date(2026, 1, 3),
    )

    assert ledger_view.opening_balance == Decimal("100.00")
    assert ledger_view.closing_balance == Decimal("85.00")
    assert [tx.running_balance for tx in ledger_view.transactions] == [
        Decimal("60.00"),
        Decimal("85.00"),
    ]


@pytest.mark.asyncio
async def test_trial_balance_aggregates_and_balances(session) -> None:
    tenant_id = uuid.uuid4()
    cash_id = uuid.uuid4()
    payable_id = uuid.uuid4()
    equity_id = uuid.uuid4()

    await _create_account(
        session,
        tenant_id=tenant_id,
        account_id=cash_id,
        code="1000",
        name="Cash",
        account_type=AccountType.ASSET,
    )
    await _create_account(
        session,
        tenant_id=tenant_id,
        account_id=payable_id,
        code="2000",
        name="Accounts Payable",
        account_type=AccountType.LIABILITY,
    )
    await _create_account(
        session,
        tenant_id=tenant_id,
        account_id=equity_id,
        code="3200",
        name="Equity",
        account_type=AccountType.EQUITY,
    )

    repo = SqlAlchemyJournalEntryRepository(session)
    service = LedgerService(repo)

    await repo.create_opening_entry(
        tenant_id=str(tenant_id),
        entry_date=date(2026, 1, 1),
        reference="JE-001",
        description="Capital",
        source_type="manual",
        created_by=None,
        lines=[
            {
                "account_id": str(cash_id),
                "debit_amount": Decimal("100.00"),
                "credit_amount": Decimal("0.00"),
            },
            {
                "account_id": str(equity_id),
                "debit_amount": Decimal("0.00"),
                "credit_amount": Decimal("100.00"),
            },
        ],
    )
    await repo.create_opening_entry(
        tenant_id=str(tenant_id),
        entry_date=date(2026, 1, 2),
        reference="JE-002",
        description="Extra capital",
        source_type="manual",
        created_by=None,
        lines=[
            {
                "account_id": str(cash_id),
                "debit_amount": Decimal("20.00"),
                "credit_amount": Decimal("0.00"),
            },
            {
                "account_id": str(equity_id),
                "debit_amount": Decimal("0.00"),
                "credit_amount": Decimal("20.00"),
            },
        ],
    )
    await repo.create_opening_entry(
        tenant_id=str(tenant_id),
        entry_date=date(2026, 1, 3),
        reference="JE-003",
        description="Vendor accrual",
        source_type="manual",
        created_by=None,
        lines=[
            {
                "account_id": str(cash_id),
                "debit_amount": Decimal("30.00"),
                "credit_amount": Decimal("0.00"),
            },
            {
                "account_id": str(payable_id),
                "debit_amount": Decimal("0.00"),
                "credit_amount": Decimal("30.00"),
            },
        ],
    )

    trial = await service.get_trial_balance(
        tenant_id=str(tenant_id),
        as_of_date=date(2026, 1, 3),
    )

    assert trial.is_balanced is True
    assert trial.total_debit_balance == Decimal("150.00")
    assert trial.total_credit_balance == Decimal("150.00")
    assert trial.imbalance == Decimal("0.00")

    by_code = {row.account_code: row for row in trial.accounts}
    assert by_code["1000"].debit_balance == Decimal("150.00")
    assert by_code["1000"].credit_balance == Decimal("0.00")
    assert by_code["2000"].credit_balance == Decimal("30.00")
    assert by_code["3200"].credit_balance == Decimal("120.00")


@pytest.mark.asyncio
async def test_account_transactions_validate_dates_and_missing_account(session) -> None:
    tenant_id = uuid.uuid4()
    cash_id = uuid.uuid4()

    await _create_account(
        session,
        tenant_id=tenant_id,
        account_id=cash_id,
        code="1000",
        name="Cash",
        account_type=AccountType.ASSET,
    )

    service = LedgerService(SqlAlchemyJournalEntryRepository(session))

    with pytest.raises(ValidationError, match="from_date cannot be after to_date"):
        await service.get_account_transactions(
            tenant_id=str(tenant_id),
            account_id=str(cash_id),
            from_date=date(2026, 2, 1),
            to_date=date(2026, 1, 1),
        )

    with pytest.raises(NotFoundError, match="Account not found"):
        await service.get_account_transactions(
            tenant_id=str(tenant_id),
            account_id=str(uuid.uuid4()),
            from_date=None,
            to_date=None,
        )
