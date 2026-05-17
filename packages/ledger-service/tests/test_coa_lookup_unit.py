from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from ledger_service.modules.opening_balance.infrastructure.coa_lookup import (
    SqlAlchemyCoaAccountResolver,
)


@pytest.mark.asyncio
async def test_resolve_codes_maps_results() -> None:
    tenant_id = str(uuid.uuid4())
    model = MagicMock()
    model.code = "1000"
    model.id = uuid.uuid4()

    session = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = [model]
    session.execute.return_value = result_mock

    resolver = SqlAlchemyCoaAccountResolver(session)
    found = await resolver.resolve_codes(tenant_id, {"1000"})
    assert found["1000"] == str(model.id)
