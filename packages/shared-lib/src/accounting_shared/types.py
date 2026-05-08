"""Domain-specific type aliases and factory functions."""

from __future__ import annotations

import uuid
from typing import Annotated, NewType

TenantId = NewType("TenantId", uuid.UUID)
UserId = NewType("UserId", uuid.UUID)
AccountId = NewType("AccountId", uuid.UUID)
JournalEntryId = NewType("JournalEntryId", uuid.UUID)

PositiveAmount = Annotated[float, "Value must be > 0"]


def new_tenant_id() -> TenantId:
    return TenantId(uuid.uuid4())


def new_user_id() -> UserId:
    return UserId(uuid.uuid4())


def new_account_id() -> AccountId:
    return AccountId(uuid.uuid4())
