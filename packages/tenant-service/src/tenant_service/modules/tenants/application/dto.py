from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class CreateTenantRequest(BaseModel):
    name: str
    slug: str


class TenantResponse(BaseModel):
    id: str
    name: str
    slug: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class TenantUserResponse(BaseModel):
    id: str
    tenant_id: str
    user_id: str
    role: str
    created_at: datetime


class AddUserRequest(BaseModel):
    user_id: str
    role: str  # "admin" | "manager" | "viewer"
