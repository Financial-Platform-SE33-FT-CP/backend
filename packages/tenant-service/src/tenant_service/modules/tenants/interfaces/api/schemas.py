from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class CreateTenantRequestSchema(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=255, pattern=r"^[a-z0-9-]+$")


class TenantResponseSchema(BaseModel):
    id: str
    name: str
    slug: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class TenantUserResponseSchema(BaseModel):
    id: str
    tenant_id: str
    user_id: str
    role: str
    created_at: datetime


class AddUserRequestSchema(BaseModel):
    user_id: str = Field(..., min_length=1)
    role: str = Field(..., pattern=r"^(admin|manager|viewer)$")


class VerifyTenantResponseSchema(BaseModel):
    exists: bool
    is_active: bool
