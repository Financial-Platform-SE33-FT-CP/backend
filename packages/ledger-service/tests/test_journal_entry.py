import uuid
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient

HEADERS_TEMPLATE = {"X-Tenant-ID": "00000000-0000-0000-0000-000000000001"}

TENANT_ID_STR = "00000000-0000-0000-0000-000000000001"
ACCOUNT_1_ID = "10000000-0000-0000-0000-000000000001"
ACCOUNT_2_ID = "20000000-0000-0000-0000-000000000001"


async def _seed_tenant(session_factory) -> None:
    from sqlalchemy import text

    async with session_factory() as session:
        await session.execute(
            text("INSERT INTO tenants (id, name) VALUES (:id, :name)"),
            {"id": TENANT_ID_STR, "name": "Test Tenant"},
        )
        await session.execute(
            text("INSERT INTO chart_of_accounts (id, code, name) VALUES (:id, :code, :name)"),
            {"id": ACCOUNT_1_ID, "code": "1000", "name": "Cash"},
        )
        await session.execute(
            text("INSERT INTO chart_of_accounts (id, code, name) VALUES (:id, :code, :name)"),
            {"id": ACCOUNT_2_ID, "code": "5000", "name": "Revenue"},
        )
        await session.commit()


async def _seed_open_period(session_factory) -> None:
    from ledger_service.modules.ledger.infrastructure.models import AccountingPeriodModel

    today = date.today()
    async with session_factory() as session:
        period = AccountingPeriodModel(
            tenant_id=uuid.UUID(TENANT_ID_STR),
            start_date=today.replace(day=1),
            end_date=today.replace(day=28),
            is_closed=False,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        session.add(period)
        await session.commit()


async def _seed_closed_period(session_factory) -> None:
    from ledger_service.modules.ledger.infrastructure.models import AccountingPeriodModel

    async with session_factory() as session:
        period = AccountingPeriodModel(
            tenant_id=uuid.UUID(TENANT_ID_STR),
            start_date=date(2020, 1, 1),
            end_date=date(2020, 12, 31),
            is_closed=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        session.add(period)
        await session.commit()


async def _seed_closed_period_today(session_factory) -> None:
    from ledger_service.modules.ledger.infrastructure.models import AccountingPeriodModel

    today = date.today()
    async with session_factory() as session:
        period = AccountingPeriodModel(
            tenant_id=uuid.UUID(TENANT_ID_STR),
            start_date=today.replace(day=1),
            end_date=today.replace(day=28),
            is_closed=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        session.add(period)
        await session.commit()


class TestCreateJournalEntry:
    """POST /ledger/journal-entries"""

    def test_create_success(self, client: TestClient, valid_payload: dict):
        import asyncio

        asyncio.run(_seed_tenant(client.app.state.session_factory))
        asyncio.run(_seed_open_period(client.app.state.session_factory))

        response = client.post(
            "/ledger/journal-entries",
            json=valid_payload,
            headers=HEADERS_TEMPLATE,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["reference"] == "JE-001"
        assert data["source_type"] == "manual"
        assert data["tenant_id"] == TENANT_ID_STR
        assert len(data["lines"]) == 2
        assert data["lines"][0]["debit_amount"] == "100.00"
        assert data["lines"][1]["credit_amount"] == "100.00"

    def test_create_returns_immutable_entry(
        self, client: TestClient, valid_payload: dict
    ):
        import asyncio

        asyncio.run(_seed_tenant(client.app.state.session_factory))
        asyncio.run(_seed_open_period(client.app.state.session_factory))

        response = client.post(
            "/ledger/journal-entries",
            json=valid_payload,
            headers=HEADERS_TEMPLATE,
        )

        assert response.status_code == 201
        entry_id = response.json()["id"]
        get_response = client.get(
            f"/ledger/journal-entries/{entry_id}",
            headers=HEADERS_TEMPLATE,
        )
        assert get_response.status_code == 200
        assert get_response.json()["id"] == entry_id

    def test_unbalanced_entry_rejected(self, client: TestClient):
        import asyncio

        asyncio.run(_seed_tenant(client.app.state.session_factory))
        asyncio.run(_seed_open_period(client.app.state.session_factory))

        payload = {
            "entry_date": date.today().isoformat(),
            "reference": "JE-BAD",
            "lines": [
                {
                    "account_id": ACCOUNT_1_ID,
                    "debit_amount": "100.00",
                    "credit_amount": "0.00",
                },
                {
                    "account_id": ACCOUNT_2_ID,
                    "debit_amount": "0.00",
                    "credit_amount": "50.00",
                },
            ],
        }

        response = client.post(
            "/ledger/journal-entries",
            json=payload,
            headers=HEADERS_TEMPLATE,
        )

        assert response.status_code == 422
        assert "not balanced" in response.json()["detail"]

    def test_single_line_rejected(self, client: TestClient):
        import asyncio

        asyncio.run(_seed_tenant(client.app.state.session_factory))
        asyncio.run(_seed_open_period(client.app.state.session_factory))

        payload = {
            "entry_date": date.today().isoformat(),
            "reference": "JE-SINGLE",
            "lines": [
                {
                    "account_id": ACCOUNT_1_ID,
                    "debit_amount": "100.00",
                    "credit_amount": "0.00",
                },
            ],
        }

        response = client.post(
            "/ledger/journal-entries",
            json=payload,
            headers=HEADERS_TEMPLATE,
        )

        assert response.status_code == 422

    def test_both_debit_and_credit_in_same_line_rejected(self, client: TestClient):
        import asyncio

        asyncio.run(_seed_tenant(client.app.state.session_factory))
        asyncio.run(_seed_open_period(client.app.state.session_factory))

        payload = {
            "entry_date": date.today().isoformat(),
            "reference": "JE-BOTH",
            "lines": [
                {
                    "account_id": ACCOUNT_1_ID,
                    "debit_amount": "100.00",
                    "credit_amount": "50.00",
                },
                {
                    "account_id": ACCOUNT_2_ID,
                    "debit_amount": "0.00",
                    "credit_amount": "50.00",
                },
            ],
        }

        response = client.post(
            "/ledger/journal-entries",
            json=payload,
            headers=HEADERS_TEMPLATE,
        )

        assert response.status_code == 422
        assert "both debit and credit" in response.json()["detail"].lower()

    def test_zero_amount_lines_rejected(self, client: TestClient):
        import asyncio

        asyncio.run(_seed_tenant(client.app.state.session_factory))
        asyncio.run(_seed_open_period(client.app.state.session_factory))

        payload = {
            "entry_date": date.today().isoformat(),
            "reference": "JE-ZERO",
            "lines": [
                {
                    "account_id": ACCOUNT_1_ID,
                    "debit_amount": "0.00",
                    "credit_amount": "0.00",
                },
                {
                    "account_id": ACCOUNT_2_ID,
                    "debit_amount": "0.00",
                    "credit_amount": "0.00",
                },
            ],
        }

        response = client.post(
            "/ledger/journal-entries",
            json=payload,
            headers=HEADERS_TEMPLATE,
        )

        assert response.status_code == 422

    def test_closed_period_rejected(self, client: TestClient, valid_payload: dict):
        import asyncio

        asyncio.run(_seed_tenant(client.app.state.session_factory))
        asyncio.run(_seed_closed_period_today(client.app.state.session_factory))

        response = client.post(
            "/ledger/journal-entries",
            json=valid_payload,
            headers=HEADERS_TEMPLATE,
        )

        assert response.status_code == 409
        assert "closed" in response.json()["detail"].lower()

    def test_missing_tenant_id_rejected(
        self, client: TestClient, valid_payload: dict
    ):
        response = client.post("/ledger/journal-entries", json=valid_payload)
        assert response.status_code == 401


class TestGetJournalEntry:
    """GET /ledger/journal-entries/{entry_id}"""

    def test_get_by_id_returns_entry_with_lines(
        self, client: TestClient, valid_payload: dict
    ):
        import asyncio

        asyncio.run(_seed_tenant(client.app.state.session_factory))
        asyncio.run(_seed_open_period(client.app.state.session_factory))

        create_resp = client.post(
            "/ledger/journal-entries",
            json=valid_payload,
            headers=HEADERS_TEMPLATE,
        )
        entry_id = create_resp.json()["id"]

        response = client.get(
            f"/ledger/journal-entries/{entry_id}",
            headers=HEADERS_TEMPLATE,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == entry_id
        assert len(data["lines"]) == 2

    def test_get_by_id_not_found(self, client: TestClient):
        response = client.get(
            "/ledger/journal-entries/nonexistent-id",
            headers=HEADERS_TEMPLATE,
        )

        assert response.status_code == 404

    def test_get_by_id_tenant_isolation(self, client: TestClient, valid_payload: dict):
        import asyncio

        asyncio.run(_seed_tenant(client.app.state.session_factory))
        asyncio.run(_seed_open_period(client.app.state.session_factory))

        create_resp = client.post(
            "/ledger/journal-entries",
            json=valid_payload,
            headers=HEADERS_TEMPLATE,
        )
        entry_id = create_resp.json()["id"]

        response = client.get(
            f"/ledger/journal-entries/{entry_id}",
            headers={"X-Tenant-ID": "99999999-9999-9999-9999-999999999999"},
        )

        assert response.status_code == 404


class TestListJournalEntries:
    """GET /ledger/journal-entries"""

    def test_list_returns_entries(self, client: TestClient, valid_payload: dict):
        import asyncio

        asyncio.run(_seed_tenant(client.app.state.session_factory))
        asyncio.run(_seed_open_period(client.app.state.session_factory))

        client.post(
            "/ledger/journal-entries",
            json=valid_payload,
            headers=HEADERS_TEMPLATE,
        )

        response = client.get(
            "/ledger/journal-entries",
            headers=HEADERS_TEMPLATE,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["count"] >= 1
        assert len(data["entries"]) >= 1

    def test_list_empty_for_new_tenant(self, client: TestClient):
        response = client.get(
            "/ledger/journal-entries",
            headers={"X-Tenant-ID": "99999999-9999-9999-9999-999999999999"},
        )

        assert response.status_code == 200
        assert response.json()["count"] == 0

    def test_list_respects_pagination(self, client: TestClient, valid_payload: dict):
        import asyncio

        asyncio.run(_seed_tenant(client.app.state.session_factory))
        asyncio.run(_seed_open_period(client.app.state.session_factory))

        for i in range(3):
            payload = {**valid_payload, "reference": f"JE-{i:03d}"}
            client.post(
                "/ledger/journal-entries",
                json=payload,
                headers=HEADERS_TEMPLATE,
            )

        response = client.get(
            "/ledger/journal-entries?limit=2",
            headers=HEADERS_TEMPLATE,
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["entries"]) == 2
        assert data["limit"] == 2
