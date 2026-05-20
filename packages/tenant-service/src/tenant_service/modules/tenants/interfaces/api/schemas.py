from __future__ import annotations

from datetime import datetime
from typing import Self

from pydantic import BaseModel, EmailStr, Field, model_validator


class CreateTenantRequestSchema(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    uen: str | None = Field(default=None, max_length=64)
    base_currency: str = Field(..., min_length=3, max_length=3)
    gst_registered: bool = False
    financial_year_start_month: int = Field(..., ge=1, le=12)
    financial_year_start_day: int = Field(..., ge=1, le=31)


class TenantSummaryResponseSchema(BaseModel):
    id: str
    name: str
    uen: str | None
    base_currency: str
    gst_registered: bool
    financial_year_start_month: int
    financial_year_start_day: int
    status: str
    role: str
    created_at: datetime


class TenantListItemResponseSchema(BaseModel):
    id: str
    name: str
    uen: str | None
    base_currency: str
    gst_registered: bool
    financial_year_start_month: int
    financial_year_start_day: int
    status: str
    role: str
    created_at: datetime


class CoaAccountResponseSchema(BaseModel):
    id: str
    code: str
    name: str
    type: str  # noqa: A003
    parent_id: str | None
    is_active: bool
    is_system_default: bool
    created_at: datetime
    updated_at: datetime


class InviteMemberRequestSchema(BaseModel):
    role: str = Field(..., min_length=1, max_length=32)
    user_id: str | None = Field(default=None, min_length=1)
    email: EmailStr | None = None

    @model_validator(mode="after")
    def one_target(self) -> Self:
        has_uid = self.user_id is not None and self.user_id != ""
        has_email = self.email is not None and str(self.email).strip() != ""
        if has_uid == has_email:
            msg = "Provide exactly one of user_id or email."
            raise ValueError(msg)
        return self


class TenantUserResponseSchema(BaseModel):
    id: str
    tenant_id: str
    user_id: str
    role: str
    created_at: datetime


class MeRoleResponseSchema(BaseModel):
    tenant_id: str
    user_id: str
    role: str
    permissions: list[str]


class MemberDetailsResponseSchema(BaseModel):
    user_id: str
    email: str
    role: str
    created_at: datetime


class UpdateMemberRoleRequestSchema(BaseModel):
    role: str = Field(..., min_length=1, max_length=32, description="OWNER, ACCOUNTANT, or VIEWER")
