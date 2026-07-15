"""Dependency injection for AR/AP Service (JWT, tenant, delegated RBAC, DB session)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from functools import lru_cache

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from accounting_shared.database import get_session
from accounting_shared.exceptions import (
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
    UnauthorizedError,
    ValidationError,
)
from accounting_shared.http_internal import post_json
from accounting_shared.middleware.tenant_context import get_current_tenant_id
from accounting_shared.types import TenantId, UserId
from ar_ap_service.config import ArApSettings
from ar_ap_service.modules.ar_ap.application.bank_statement import BankStatementService
from ar_ap_service.modules.ar_ap.application.bill_service import BillService
from ar_ap_service.modules.ar_ap.application.reconciliation import ReconciliationService
from ar_ap_service.modules.ar_ap.application.services import (
    CreditNoteService,
    GstService,
    InvoiceService,
    PaymentService,
)
from ar_ap_service.modules.ar_ap.infrastructure.repository import (
    SqlAccountReader,
    SqlAlchemyBankAccountRepository,
    SqlAlchemyBankTransactionRepository,
    SqlAlchemyBillPaymentRepository,
    SqlAlchemyBillRepository,
    SqlAlchemyCreditNoteRepository,
    SqlAlchemyCustomerRepository,
    SqlAlchemyGstRepository,
    SqlAlchemyInvoiceRepository,
    SqlAlchemyPaymentRepository,
    SqlAlchemyVendorRepository,
    SqlLedgerPoster,
)

security_scheme = HTTPBearer(auto_error=False)


@lru_cache
def get_settings() -> ArApSettings:
    """Get cached AR/AP settings."""
    return ArApSettings()


async def get_access_token_payload(
    credentials: HTTPAuthorizationCredentials | None = Depends(security_scheme),
    settings: ArApSettings = Depends(get_settings),
) -> dict[str, object]:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise UnauthorizedError("Not authenticated.")
    try:
        payload: dict[str, object] = jwt.decode(
            credentials.credentials,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
        return payload
    except JWTError as e:
        raise UnauthorizedError("Not authenticated.") from e


async def get_current_user_id(
    payload: dict[str, object] = Depends(get_access_token_payload),
) -> UserId:
    if payload.get("type") != "access":
        raise UnauthorizedError("Not authenticated.")
    sub = payload.get("sub")
    if not sub:
        raise UnauthorizedError("Not authenticated.")
    try:
        return UserId(uuid.UUID(str(sub)))
    except ValueError as e:
        raise UnauthorizedError("Not authenticated.") from e


def require_tenant_id() -> TenantId:
    raw = get_current_tenant_id()
    if raw is None:
        raise ValidationError("X-Tenant-ID header is required.")
    return TenantId(raw)


async def authorize_via_tenant_service(
    *,
    settings: ArApSettings,
    user_id: UserId,
    tenant_id: TenantId,
    permission: str,
) -> None:
    """Delegate permission checks to tenant-service (single source of truth, US-3)."""
    token = (settings.tenant_internal_api_token or "").strip()
    if not token:
        raise ServiceUnavailableError("RBAC is not configured for this service.")
    base = (settings.tenant_service_url or "").strip().rstrip("/")
    if not base:
        raise ServiceUnavailableError("Tenant service URL is not configured.")
    url = f"{base}/internal/authorization/check"
    try:
        status_code, data = await post_json(
            url,
            headers={"X-Internal-Token": token},
            body={
                "user_id": str(user_id),
                "tenant_id": str(tenant_id),
                "permission": permission,
            },
        )
    except OSError as e:
        raise ServiceUnavailableError("Unable to reach tenant authorization service.") from e
    if status_code == 401:
        raise ServiceUnavailableError("Tenant authorization service rejected the internal token.")
    if status_code != 200:
        detail = data if isinstance(data, str) else str(data)
        raise ServiceUnavailableError(
            f"Tenant authorization service returned HTTP {status_code}: {detail}"
        )
    if not isinstance(data, dict):
        raise ServiceUnavailableError("Tenant authorization service returned an invalid response.")
    if data.get("allowed") is True:
        return
    reason = data.get("reason")
    if reason == "tenant_not_found":
        raise NotFoundError("Tenant not found.")
    if reason == "not_member":
        raise ForbiddenError("Not a member of this tenant.")
    raise ForbiddenError("You do not have permission for this action.")


class RequireArApPermission:
    """Route dependency: JWT user + X-Tenant-ID + delegated RBAC for one permission."""

    def __init__(self, permission: str) -> None:
        if not permission:
            msg = "Permission is required."
            raise ValueError(msg)
        self.permission = permission

    async def __call__(
        self,
        tenant_id: TenantId = Depends(require_tenant_id),
        user_id: UserId = Depends(get_current_user_id),
        settings: ArApSettings = Depends(get_settings),
    ) -> None:
        await authorize_via_tenant_service(
            settings=settings,
            user_id=user_id,
            tenant_id=tenant_id,
            permission=self.permission,
        )


async def get_async_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Yield a session that commits on success and rolls back on error."""
    factory = request.app.state.session_factory
    async for session in get_session(factory):
        yield session


async def get_invoice_service(
    session: AsyncSession = Depends(get_async_session),
    settings: ArApSettings = Depends(get_settings),
) -> InvoiceService:
    return InvoiceService(
        invoices=SqlAlchemyInvoiceRepository(session),
        customers=SqlAlchemyCustomerRepository(session),
        accounts=SqlAccountReader(session),
        gst=SqlAlchemyGstRepository(session),
        ledger=SqlLedgerPoster(session),
        settings=settings,
    )


async def get_payment_service(
    session: AsyncSession = Depends(get_async_session),
    settings: ArApSettings = Depends(get_settings),
) -> PaymentService:
    return PaymentService(
        payments=SqlAlchemyPaymentRepository(session),
        invoices=SqlAlchemyInvoiceRepository(session),
        customers=SqlAlchemyCustomerRepository(session),
        accounts=SqlAccountReader(session),
        ledger=SqlLedgerPoster(session),
        settings=settings,
    )


async def get_credit_note_service(
    session: AsyncSession = Depends(get_async_session),
    settings: ArApSettings = Depends(get_settings),
) -> CreditNoteService:
    return CreditNoteService(
        credit_notes=SqlAlchemyCreditNoteRepository(session),
        invoices=SqlAlchemyInvoiceRepository(session),
        customers=SqlAlchemyCustomerRepository(session),
        accounts=SqlAccountReader(session),
        gst=SqlAlchemyGstRepository(session),
        ledger=SqlLedgerPoster(session),
        settings=settings,
    )


async def get_gst_service(
    session: AsyncSession = Depends(get_async_session),
) -> GstService:
    return GstService(gst=SqlAlchemyGstRepository(session))


async def get_bank_transaction_repository(
    session: AsyncSession = Depends(get_async_session),
) -> SqlAlchemyBankTransactionRepository:
    return SqlAlchemyBankTransactionRepository(session)


async def get_bank_statement_service(
    bank_txn_repo: SqlAlchemyBankTransactionRepository = Depends(get_bank_transaction_repository),
) -> BankStatementService:
    return BankStatementService(bank_txn_repo=bank_txn_repo)


async def get_reconciliation_service(
    bank_txn_repo: SqlAlchemyBankTransactionRepository = Depends(get_bank_transaction_repository),
    session: AsyncSession = Depends(get_async_session),
    settings: ArApSettings = Depends(get_settings),
) -> ReconciliationService:
    return ReconciliationService(
        bank_txn_repo=bank_txn_repo,
        invoice_repo=SqlAlchemyInvoiceRepository(session),
        payment_repo=SqlAlchemyPaymentRepository(session),
        ledger_poster=SqlLedgerPoster(session),
        bill_repo=SqlAlchemyBillRepository(session),
        accounts=SqlAccountReader(session),
        settings=settings,
    )


async def get_bank_account_repository(
    session: AsyncSession = Depends(get_async_session),
) -> SqlAlchemyBankAccountRepository:
    return SqlAlchemyBankAccountRepository(session)


async def get_bill_service(
    session: AsyncSession = Depends(get_async_session),
    settings: ArApSettings = Depends(get_settings),
) -> BillService:
    return BillService(
        bills=SqlAlchemyBillRepository(session),
        vendors=SqlAlchemyVendorRepository(session),
        accounts=SqlAccountReader(session),
        gst=SqlAlchemyGstRepository(session),
        ledger=SqlLedgerPoster(session),
        bill_payments=SqlAlchemyBillPaymentRepository(session),
    )
