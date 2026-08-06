"""Fire-and-forget audit log HTTP client (EPIC 11).

The audit client writes audit entries to the audit-service internal endpoint.
It is deliberately non-blocking: a failed or slow audit write must never
affect the business operation that triggered it.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Any

import structlog

from accounting_shared.http_internal import post_json

logger = structlog.get_logger(__name__)

AUDIT_LOG_PATH = "/audit/audit-logs"
AUDIT_CLIENT_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class CreateAuditLogDTO:
    """Payload for a single audit log entry."""

    tenant_id: uuid.UUID
    user_id: uuid.UUID
    action: str
    entity_type: str
    entity_id: str
    changes: dict[str, Any] | None = None

    def as_payload(self) -> dict[str, Any]:
        """Serialize to the JSON body expected by the audit-service endpoint."""
        return {
            "tenant_id": str(self.tenant_id),
            "user_id": str(self.user_id),
            "action": self.action,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "changes": self.changes,
        }


class AuditHttpClient:
    """HTTP client for the audit-service internal ``POST /audit/audit-logs`` endpoint.

    Fire-and-forget by design: ``log_in_background`` schedules the write and
    returns immediately; ``log`` swallows every failure and only logs a
    warning. Callers are never blocked on the audit service.
    """

    def __init__(self, audit_service_url: str, internal_token: str) -> None:
        self._base_url = (audit_service_url or "").strip().rstrip("/")
        self._internal_token = internal_token or ""
        self._tasks: set[asyncio.Task[None]] = set()

    @property
    def is_configured(self) -> bool:
        """True when both the service URL and internal token are set."""
        return bool(self._base_url and self._internal_token)

    def log_in_background(self, dto: CreateAuditLogDTO) -> None:
        """Schedule an audit log write without blocking the caller.

        The task is tracked so it is not garbage-collected mid-flight; when
        the audit service is unreachable or unconfigured the event is dropped
        with a warning log. Never raises, even outside an event loop.
        """
        if not self.is_configured:
            logger.warning(
                "audit_client_unconfigured",
                entity_type=dto.entity_type,
                entity_id=dto.entity_id,
                action=dto.action,
            )
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning(
                "audit_client_no_event_loop",
                entity_type=dto.entity_type,
                entity_id=dto.entity_id,
                action=dto.action,
            )
            return
        task = loop.create_task(self.log(dto))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def log(self, dto: CreateAuditLogDTO) -> None:
        """POST one audit log entry. Never raises."""
        if not self.is_configured:
            logger.warning(
                "audit_client_unconfigured",
                entity_type=dto.entity_type,
                entity_id=dto.entity_id,
                action=dto.action,
            )
            return
        url = f"{self._base_url}{AUDIT_LOG_PATH}"
        try:
            status_code, data = await post_json(
                url,
                headers={"X-Internal-Token": self._internal_token},
                body=dto.as_payload(),
                timeout=AUDIT_CLIENT_TIMEOUT_SECONDS,
            )
        except Exception as exc:  # network, timeout, DNS — audit must never block the caller
            logger.warning(
                "audit_log_post_failed",
                url=url,
                entity_type=dto.entity_type,
                entity_id=dto.entity_id,
                action=dto.action,
                error=str(exc),
            )
            return
        if status_code >= 400:
            detail = data if isinstance(data, str) else str(data)
            logger.warning(
                "audit_log_rejected",
                url=url,
                status_code=status_code,
                entity_type=dto.entity_type,
                entity_id=dto.entity_id,
                action=dto.action,
                detail=detail,
            )


def make_audit_client(
    audit_service_url: str,
    internal_token: str,
) -> AuditHttpClient:
    """Construct an :class:`AuditHttpClient` (keeps imports light at call sites)."""
    return AuditHttpClient(audit_service_url=audit_service_url, internal_token=internal_token)
