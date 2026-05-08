from functools import lru_cache

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from ledger_service.config import LedgerSettings


@lru_cache
def get_settings() -> LedgerSettings:
    return LedgerSettings()


async def get_async_session(request: Request) -> AsyncSession:
    factory = request.app.state.session_factory
    async with factory() as session:
        yield session
