"""Slice 5: Audit REST API integration tests (real SQLite via TestClient)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from jose import jwt

from audit_service import deps

TENANT_ID = "00000000-0000-0000-0000-000000000001"
TEST_USER_ID = uuid.UUID("ffffffff-0000-0000-0000-000000000001")
INTERNAL_TOKEN = "test-internal-token"

BASE = "/audit/audit-logs"


@pytest.fixture(autouse=True)
def _override_rbac(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    """Bypass the outbound tenant-service RBAC call (JWT itself is real)."""

    async def _mock_authorize_via_tenant_service(**kwargs):
        return None

    monkeypatch.setattr(deps, "authorize_via_tenant_service", _mock_authorize_via_tenant_service)
    yield


def _auth_headers() -> dict[str, str]:
    settings = deps.get_settings()
    token = jwt.encode(
        {"sub": str(TEST_USER_ID), "type": "access"},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    return {"Authorization": f"Bearer {token}", "X-Tenant-ID": TENANT_ID}


def _internal_headers() -> dict[str, str]:
    return {"X-Internal-Token": INTERNAL_TOKEN}


def _log_payload(**overrides) -> dict:
    payload = {
        "tenant_id": TENANT_ID,
        "user_id": str(TEST_USER_ID),
        "action": "created",
        "entity_type": "journal_entry",
        "entity_id": "je-001",
        "changes": {"reference": "JE-001"},
    }
    payload.update(overrides)
    return payload


def _create_log(client: TestClient, **overrides) -> dict:
    resp = client.post(BASE, json=_log_payload(**overrides), headers=_internal_headers())
    assert resp.status_code == 201, resp.text
    return resp.json()


class TestCreateAuditLogInternal:
    def test_create_with_valid_internal_token(self, client: TestClient):
        data = _create_log(client)
        assert data["action"] == "created"
        assert data["entity_type"] == "journal_entry"
        assert data["entity_id"] == "je-001"
        assert data["changes"] == {"reference": "JE-001"}
        assert data["timestamp"] is not None

    def test_create_without_token_rejected(self, client: TestClient):
        resp = client.post(BASE, json=_log_payload())
        assert resp.status_code == 401

    def test_create_with_wrong_token_rejected(self, client: TestClient):
        resp = client.post(BASE, json=_log_payload(), headers={"X-Internal-Token": "nope"})
        assert resp.status_code == 401

    def test_create_rejects_blank_action(self, client: TestClient):
        resp = client.post(
            BASE,
            json=_log_payload(action=""),
            headers=_internal_headers(),
        )
        assert resp.status_code == 422


class TestGetAuditLog:
    def test_get_existing_log(self, client: TestClient):
        created = _create_log(client)
        resp = client.get(f"{BASE}/{created['id']}", headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == created["id"]
        assert data["action"] == "created"

    def test_get_missing_log_returns_404(self, client: TestClient):
        resp = client.get(f"{BASE}/{uuid.uuid4()}", headers=_auth_headers())
        assert resp.status_code == 404

    def test_get_requires_auth(self, client: TestClient):
        created = _create_log(client)
        resp = client.get(f"{BASE}/{created['id']}", headers={"X-Tenant-ID": TENANT_ID})
        assert resp.status_code == 401

    def test_get_requires_tenant_header(self, client: TestClient):
        created = _create_log(client)
        settings = deps.get_settings()
        token = jwt.encode(
            {"sub": str(TEST_USER_ID), "type": "access"},
            settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
        )
        resp = client.get(
            f"{BASE}/{created['id']}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422


class TestListAuditLogs:
    def test_list_returns_created_logs(self, client: TestClient):
        _create_log(client)
        resp = client.get(BASE, headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["action"] == "created"
        assert data["items"][0]["entity_type"] == "journal_entry"

    def test_list_with_action_filter(self, client: TestClient):
        _create_log(client, action="created", entity_id="je-1")
        _create_log(client, action="reversed", entity_id="je-2")
        resp = client.get(BASE, params={"action": "created"}, headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["items"][0]["action"] == "created"

    def test_list_with_entity_type_filter(self, client: TestClient):
        _create_log(client, entity_type="journal_entry", entity_id="je-1")
        _create_log(client, entity_type="invoice", entity_id="inv-1")
        resp = client.get(BASE, params={"entity_type": "invoice"}, headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["items"][0]["entity_type"] == "invoice"

    def test_list_with_date_range_filter(self, client: TestClient):
        _create_log(client)
        today = datetime.now(UTC).date()
        resp = client.get(
            BASE,
            params={
                "from_date": (today - timedelta(days=1)).isoformat(),
                "to_date": (today + timedelta(days=1)).isoformat(),
            },
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        assert resp.json()["count"] == 1

        future = (today + timedelta(days=30)).isoformat()
        resp = client.get(
            BASE,
            params={"from_date": future},
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    def test_list_pagination(self, client: TestClient):
        for i in range(3):
            _create_log(client, entity_id=f"je-{i}")
        resp = client.get(BASE, params={"limit": 2}, headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        assert data["offset"] == 0
        assert data["limit"] == 2

        resp = client.get(BASE, params={"limit": 2, "offset": 2}, headers=_auth_headers())
        assert resp.status_code == 200
        assert resp.json()["count"] == 1

    def test_list_scoped_to_tenant(self, client: TestClient):
        _create_log(client, tenant_id="00000000-0000-0000-0000-000000000099")
        resp = client.get(BASE, headers=_auth_headers())
        assert resp.status_code == 200
        assert resp.json()["count"] == 0
