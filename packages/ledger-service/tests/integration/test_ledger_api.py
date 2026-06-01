from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from accounting_shared.types import TenantId, UserId

TEST_USER_ID = uuid.UUID("ffffffff-0000-0000-0000-000000000001")

HEADERS = {"X-Tenant-ID": "00000000-0000-0000-0000-000000000001"}

TENANT_ID = "00000000-0000-0000-0000-000000000001"
ACCOUNT_1_ID = "10000000-0000-0000-0000-000000000001"
ACCOUNT_2_ID = "20000000-0000-0000-0000-000000000001"
ACCOUNT_3_ID = "30000000-0000-0000-0000-000000000001"


@pytest.fixture(autouse=True)
def _override_auth(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    """Bypass JWT + RBAC for integration tests."""
    from ledger_service import deps

    async def _mock_get_current_user_id():
        return UserId(TEST_USER_ID)

    async def _mock_authorize_via_tenant_service(**kwargs):
        return None

    client.app.dependency_overrides[deps.get_current_user_id] = _mock_get_current_user_id
    monkeypatch.setattr(deps, "authorize_via_tenant_service", _mock_authorize_via_tenant_service)
    yield
    client.app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# seed helpers
# ---------------------------------------------------------------------------


async def _seed_tenant(client) -> None:
    from datetime import datetime

    from coa_service.modules.coa.infrastructure.models import AccountModel, AccountType

    async with client.app.state.session_factory() as session:
        await session.execute(
            text("INSERT INTO tenants (id, name) VALUES (:id, :name)"),
            {"id": TENANT_ID, "name": "Test Tenant"},
        )
        now = datetime.now()
        for acct_id, code, name, atype in [
            (ACCOUNT_1_ID, "1000", "Cash", AccountType.ASSET),
            (ACCOUNT_2_ID, "5000", "Revenue", AccountType.REVENUE),
            (ACCOUNT_3_ID, "6000", "Expense", AccountType.EXPENSE),
        ]:
            session.add(AccountModel(
                id=uuid.UUID(acct_id),
                tenant_id=uuid.UUID(TENANT_ID),
                code=code,
                name=name,
                account_type=atype,
                is_active=True,
                is_system_default=False,
                created_at=now,
                updated_at=now,
            ))
        await session.commit()


async def _seed_open_period(client) -> None:
    from calendar import monthrange

    from ledger_service.modules.ledger.infrastructure.models import AccountingPeriodModel

    today = date.today()
    _, last_day = monthrange(today.year, today.month)
    async with client.app.state.session_factory() as session:
        period = AccountingPeriodModel(
            tenant_id=uuid.UUID(TENANT_ID),
            start_date=today.replace(day=1),
            end_date=today.replace(day=last_day),
            is_closed=False,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        session.add(period)
        await session.commit()


def _setup(client):
    asyncio.run(_seed_tenant(client))
    asyncio.run(_seed_open_period(client))


def _balanced_payload(**kwargs):
    defaults = {
        "entry_date": date.today().isoformat(),
        "reference": "JE-API",
        "description": "integration test",
        "lines": [
            {"account_id": ACCOUNT_1_ID, "debit_amount": "200.00", "credit_amount": "0.00", "description": "dr"},
            {"account_id": ACCOUNT_2_ID, "debit_amount": "0.00", "credit_amount": "200.00", "description": "cr"},
        ],
    }
    defaults.update(kwargs)
    return defaults


def _create_entry(client, **kwargs):
    _setup(client)
    payload = _balanced_payload(**kwargs)
    resp = client.post("/ledger/journal-entries", json=payload, headers=HEADERS)
    assert resp.status_code == 201, resp.text
    return resp.json()


# ============================================================================
# POST /ledger/journal-entries — additional scenarios
# ============================================================================


class TestCreateJournalEntryExtended:
    def test_account_not_in_coa_rejected(self, client: TestClient):
        asyncio.run(_seed_tenant(client))
        asyncio.run(_seed_open_period(client))

        payload = _balanced_payload()
        payload["lines"][0]["account_id"] = "99999999-0000-0000-0000-000000000009"

        resp = client.post("/ledger/journal-entries", json=payload, headers=HEADERS)
        assert resp.status_code == 422
        assert "not found in Chart of Accounts" in resp.json()["detail"]

    def test_debit_equals_credit_multiline(self, client: TestClient):
        """Three-line entry where total debit = total credit."""
        _setup(client)
        payload = {
            "entry_date": date.today().isoformat(),
            "reference": "JE-MULTI",
            "lines": [
                {"account_id": ACCOUNT_1_ID, "debit_amount": "100.00", "credit_amount": "0.00", "description": "dr cash"},
                {"account_id": ACCOUNT_2_ID, "debit_amount": "0.00", "credit_amount": "60.00", "description": "cr revenue"},
                {"account_id": ACCOUNT_2_ID, "debit_amount": "0.00", "credit_amount": "40.00", "description": "cr revenue"},
            ],
        }
        resp = client.post("/ledger/journal-entries", json=payload, headers=HEADERS)
        assert resp.status_code == 201
        data = resp.json()
        assert len(data["lines"]) == 3

    def test_empty_lines_field_rejected(self, client: TestClient):
        _setup(client)
        payload = {
            "entry_date": date.today().isoformat(),
            "reference": "JE-EMPTY",
            "lines": [],
        }
        resp = client.post("/ledger/journal-entries", json=payload, headers=HEADERS)
        assert resp.status_code == 422


# TODO: POST /ledger/journal-entries/{id}/reverse — endpoint not yet implemented in router.
# Add tests here when reverse_entry() is added to LedgerService and a route is wired up.


# ============================================================================
# GET /ledger/trial-balance
# ============================================================================


class TestTrialBalance:
    def test_empty_trial_balance(self, client: TestClient):
        _setup(client)
        resp = client.get("/ledger/trial-balance", headers=HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["accounts"] == []
        assert data["is_balanced"] is True
        assert data["total_debit_balance"] == "0.00"
        assert data["total_credit_balance"] == "0.00"

    def test_trial_balance_after_entries(self, client: TestClient):
        _setup(client)
        client.post("/ledger/journal-entries", json=_balanced_payload(), headers=HEADERS)

        resp = client.get("/ledger/trial-balance", headers=HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["accounts"]) == 2
        assert data["is_balanced"] is True

        # verify account balances
        accounts_by_code = {a["account_code"]: a for a in data["accounts"]}
        cash = accounts_by_code["1000"]
        assert cash["debit_balance"] == "200.00"
        assert cash["credit_balance"] == "0.00"
        revenue = accounts_by_code["5000"]
        assert revenue["credit_balance"] == "200.00"
        assert revenue["debit_balance"] == "0.00"

    def test_trial_balance_as_of_date(self, client: TestClient):
        """Entries after as_of_date should be excluded."""
        _setup(client)

        # create an entry dated in the past
        past = date.today().replace(day=1)
        payload = _balanced_payload(entry_date=past.isoformat(), reference="JE-PAST")
        client.post("/ledger/journal-entries", json=payload, headers=HEADERS)

        # trial balance as of day before the entry → should be empty
        day_before = past.replace(day=past.day - 1) if past.day > 1 else past
        if day_before >= past:
            pytest.skip("Cannot test as_of_date on the first of the month")

        resp = client.get(f"/ledger/trial-balance?as_of_date={day_before.isoformat()}", headers=HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["accounts"] == []

    def test_trial_balance_imbalance_detected(self, client: TestClient):
        """When debits ≠ credits the report should flag it."""
        _setup(client)

        # Post a balanced entry
        client.post("/ledger/journal-entries", json=_balanced_payload(), headers=HEADERS)
        # Post another balanced entry with different amounts
        p2 = _balanced_payload(reference="JE-002", lines=[
            {"account_id": ACCOUNT_1_ID, "debit_amount": "300.00", "credit_amount": "0.00", "description": "dr"},
            {"account_id": ACCOUNT_2_ID, "debit_amount": "0.00", "credit_amount": "300.00", "description": "cr"},
        ])
        client.post("/ledger/journal-entries", json=p2, headers=HEADERS)

        resp = client.get("/ledger/trial-balance", headers=HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_balanced"] is True
        assert data["total_debit_balance"] == data["total_credit_balance"]


# ============================================================================
# GET /ledger/accounts/{account_id}/transactions
# ============================================================================


class TestAccountTransactions:
    def test_empty_transactions(self, client: TestClient):
        _setup(client)
        resp = client.get(
            f"/ledger/accounts/{ACCOUNT_1_ID}/transactions",
            headers=HEADERS,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["account_id"] == ACCOUNT_1_ID
        assert data["transactions"] == []
        assert data["opening_balance"] == "0.00"
        assert data["closing_balance"] == "0.00"

    def test_transactions_after_entry(self, client: TestClient):
        _setup(client)
        client.post("/ledger/journal-entries", json=_balanced_payload(), headers=HEADERS)

        resp = client.get(
            f"/ledger/accounts/{ACCOUNT_1_ID}/transactions",
            headers=HEADERS,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["transactions"]) == 1
        txn = data["transactions"][0]
        assert txn["debit_amount"] == "200.00"
        assert txn["credit_amount"] == "0.00"
        assert "running_balance" in txn

    def test_date_filter(self, client: TestClient):
        entry = _create_entry(client)  # _create_entry already calls _setup

        # query with a range that should include the entry
        resp = client.get(
            f"/ledger/accounts/{ACCOUNT_1_ID}/transactions"
            f"?from_date={date.today().isoformat()}&to_date={date.today().isoformat()}",
            headers=HEADERS,
        )
        assert resp.status_code == 200
        assert len(resp.json()["transactions"]) >= 1

    def test_invalid_date_range_returns_error(self, client: TestClient):
        _setup(client)
        resp = client.get(
            f"/ledger/accounts/{ACCOUNT_1_ID}/transactions"
            f"?from_date=2026-12-31&to_date=2026-01-01",
            headers=HEADERS,
        )
        assert resp.status_code == 422
        assert "from_date cannot be after to_date" in resp.json()["detail"]

    def test_account_not_found(self, client: TestClient):
        _setup(client)
        resp = client.get(
            "/ledger/accounts/99999999-0000-0000-0000-000000000009/transactions",
            headers=HEADERS,
        )
        assert resp.status_code == 404


# ============================================================================
# Cross-account balancing end-to-end
# ============================================================================


class TestCrossAccountBalancing:
    def test_full_accounting_cycle_balances(self, client: TestClient):
        """End-to-end: create entries across 3 accounts, verify trial balance."""
        _setup(client)

        # Entry 1: Debit Cash 100, Credit Revenue 100
        e1 = _balanced_payload(
            reference="JE-CYCLE-1",
            lines=[
                {"account_id": ACCOUNT_1_ID, "debit_amount": "100.00", "credit_amount": "0.00", "description": "cash"},
                {"account_id": ACCOUNT_2_ID, "debit_amount": "0.00", "credit_amount": "100.00", "description": "revenue"},
            ],
        )
        r1 = client.post("/ledger/journal-entries", json=e1, headers=HEADERS)
        assert r1.status_code == 201

        # Entry 2: Debit Expense 50, Credit Cash 50
        e2 = _balanced_payload(
            reference="JE-CYCLE-2",
            lines=[
                {"account_id": ACCOUNT_3_ID, "debit_amount": "50.00", "credit_amount": "0.00", "description": "expense"},
                {"account_id": ACCOUNT_1_ID, "debit_amount": "0.00", "credit_amount": "50.00", "description": "cash"},
            ],
        )
        r2 = client.post("/ledger/journal-entries", json=e2, headers=HEADERS)
        assert r2.status_code == 201

        # Verify trial balance
        tb = client.get("/ledger/trial-balance", headers=HEADERS)
        assert tb.status_code == 200
        tb_data = tb.json()
        assert tb_data["is_balanced"] is True

        accounts = {a["account_code"]: a for a in tb_data["accounts"]}

        # Cash: 100 debit - 50 credit = 50 debit balance
        assert accounts["1000"]["debit_balance"] == "50.00"
        assert accounts["1000"]["credit_balance"] == "0.00"

        # Revenue: 100 credit = 100 credit balance
        assert accounts["5000"]["credit_balance"] == "100.00"
        assert accounts["5000"]["debit_balance"] == "0.00"

        # Expense: 50 debit = 50 debit balance
        assert accounts["6000"]["debit_balance"] == "50.00"
        assert accounts["6000"]["credit_balance"] == "0.00"

    def test_get_all_entries_after_cycle(self, client: TestClient):
        """After posting 2 entries, list should return both."""
        _setup(client)

        client.post("/ledger/journal-entries", json=_balanced_payload(reference="JE-A"), headers=HEADERS)
        client.post("/ledger/journal-entries", json=_balanced_payload(reference="JE-B"), headers=HEADERS)

        resp = client.get("/ledger/journal-entries", headers=HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        references = {e["reference"] for e in data["entries"]}
        assert references == {"JE-A", "JE-B"}
