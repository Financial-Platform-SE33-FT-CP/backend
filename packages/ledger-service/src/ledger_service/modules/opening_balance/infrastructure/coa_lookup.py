"""Resolve chart of accounts codes via shared database."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from coa_service.modules.coa.infrastructure.models import AccountModel

from ledger_service.modules.opening_balance.application.validator import CoaAccountResolver


class SqlAlchemyCoaAccountResolver(CoaAccountResolver):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def resolve_codes(
        self, tenant_id: str, codes: set[str]
    ) -> dict[str, str]:
        if not codes:
            return {}
        tid = uuid.UUID(tenant_id)
        stmt = select(AccountModel).where(
            AccountModel.tenant_id == tid,
            AccountModel.code.in_(codes),
            AccountModel.is_active.is_(True),
        )
        result = await self._session.execute(stmt)
        return {model.code: str(model.id) for model in result.scalars().all()}
