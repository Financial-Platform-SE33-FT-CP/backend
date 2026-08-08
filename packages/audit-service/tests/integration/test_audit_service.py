"""Slice 4: AuditService + repository integration tests (real SQLite)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from accounting_shared.exceptions import NotFoundError, ValidationError
from audit_service.modules.audit.application.services import AuditService
from audit_service.modules.audit.domain.entities import AuditLog
from audit_service.modules.audit.infrastructure.repository import (
    SqlAlchemyAuditLogRepository,
)

TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
OTHER_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")
USER_ID = uuid.UUID("ffffffff-0000-0000-0000-000000000001")


def _service(session):
    return AuditService(SqlAlchemyAuditLogRepository(session))


async def _seed_log(session, *, tenant_id=TENANT_ID, action="created", entity_type="journal_entry",
                    entity_id="je-1", changes=None, timestamp=None) -> AuditLog:
    repo = SqlAlchemyAuditLogRepository(session)
    log = AuditLog(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        user_id=USER_ID,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        changes=changes,
        timestamp=timestamp or datetime.now(UTC),
    )
    return await repo.create(log)


class TestCreateAuditLog:
    async def test_create_persists_and_can_be_read_back(self, session):
        service = _service(session)
        created = await service.create_audit_log(
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            action="created",
            entity_type="journal_entry",
            entity_id="je-001",
            changes={"reference": "JE-001"},
        )
        assert created.id is not None
        assert created.action == "created"
        assert created.entity_type == "journal_entry"
        assert created.entity_id == "je-001"
        assert created.changes == {"reference": "JE-001"}
        assert created.timestamp is not None

        fetched = await service.get_audit_log(TENANT_ID, created.id)
        assert fetched.id == created.id
        assert fetched.action == "created"
        assert fetched.changes == {"reference": "JE-001"}

    async def test_create_requires_non_empty_fields(self, session):
        service = _service(session)
        with pytest.raises(ValidationError):
            await service.create_audit_log(
                tenant_id=TENANT_ID,
                user_id=USER_ID,
                action="",
                entity_type="journal_entry",
                entity_id="je-001",
            )
        with pytest.raises(ValidationError):
            await service.create_audit_log(
                tenant_id=TENANT_ID,
                user_id=USER_ID,
                action="created",
                entity_type="  ",
                entity_id="je-001",
            )


class TestGetAuditLog:
    async def test_get_missing_raises_not_found(self, session):
        service = _service(session)
        with pytest.raises(NotFoundError):
            await service.get_audit_log(TENANT_ID, uuid.uuid4())

    async def test_get_scoped_to_tenant(self, session):
        service = _service(session)
        log = await _seed_log(session)
        # Same log id, different tenant -> not visible.
        with pytest.raises(NotFoundError):
            await service.get_audit_log(OTHER_TENANT_ID, log.id)


class TestListAuditLogs:
    async def test_list_returns_created_logs(self, session):
        service = _service(session)
        created = await service.create_audit_log(
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            action="created",
            entity_type="invoice",
            entity_id="inv-1",
        )
        logs = await service.list_audit_logs(TENANT_ID)
        assert any(log.id == created.id for log in logs)

    async def test_list_excludes_other_tenants(self, session):
        service = _service(session)
        await _seed_log(session, tenant_id=OTHER_TENANT_ID)
        logs = await service.list_audit_logs(TENANT_ID)
        assert logs == []

    async def test_action_filter(self, session):
        service = _service(session)
        await _seed_log(session, action="created", entity_id="je-1")
        await _seed_log(session, action="reversed", entity_id="je-2")
        logs = await service.list_audit_logs(TENANT_ID, action="created")
        assert [log.action for log in logs] == ["created"]
        assert len(logs) == 1

    async def test_entity_type_filter(self, session):
        service = _service(session)
        await _seed_log(session, entity_type="journal_entry", entity_id="je-1")
        await _seed_log(session, entity_type="invoice", entity_id="inv-1")
        logs = await service.list_audit_logs(TENANT_ID, entity_type="invoice")
        assert [log.entity_type for log in logs] == ["invoice"]
        assert len(logs) == 1

    async def test_date_range_filter(self, session):
        service = _service(session)
        jan_log = await _seed_log(
            session, entity_id="je-1",
            timestamp=datetime(2026, 1, 15, 10, 0, 0),
        )
        feb_log = await _seed_log(
            session, entity_id="je-2",
            timestamp=datetime(2026, 2, 20, 12, 0, 0),
        )

        from datetime import date

        feb_only = await service.list_audit_logs(TENANT_ID, from_date=date(2026, 2, 1))
        assert [log.id for log in feb_only] == [feb_log.id]

        jan_only = await service.list_audit_logs(TENANT_ID, to_date=date(2026, 1, 31))
        assert [log.id for log in jan_only] == [jan_log.id]

        jan_window = await service.list_audit_logs(
            TENANT_ID,
            from_date=date(2026, 1, 1),
            to_date=date(2026, 1, 31),
        )
        assert [log.id for log in jan_window] == [jan_log.id]

    async def test_pagination_orders_newest_first(self, session):
        service = _service(session)
        log_a = await _seed_log(session, entity_id="je-1", timestamp=datetime(2026, 1, 1, 1, 0, 0))
        log_b = await _seed_log(session, entity_id="je-2", timestamp=datetime(2026, 1, 2, 1, 0, 0))
        log_c = await _seed_log(session, entity_id="je-3", timestamp=datetime(2026, 1, 3, 1, 0, 0))

        first_page = await service.list_audit_logs(TENANT_ID, limit=2, offset=0)
        assert [log.id for log in first_page] == [log_c.id, log_b.id]

        second_page = await service.list_audit_logs(TENANT_ID, limit=2, offset=2)
        assert [log.id for log in second_page] == [log_a.id]
