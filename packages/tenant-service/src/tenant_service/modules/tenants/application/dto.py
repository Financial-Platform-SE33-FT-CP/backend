from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class CreateTenantRequest(BaseModel):
    name: str
    uen: str | None = None
    base_currency: str
    gst_registered: bool = False
    financial_year_start_month: int = Field(ge=1, le=12)
    financial_year_start_day: int = Field(ge=1, le=31)


class TenantSummaryResponse(BaseModel):
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


class TenantListItemResponse(BaseModel):
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


class CoaAccountResponse(BaseModel):
    id: str
    code: str
    name: str
    type: str  # noqa: A003
    parent_id: str | None
    is_active: bool
    is_system_default: bool
    created_at: datetime
    updated_at: datetime


class InviteMemberRequest(BaseModel):
    """Invite by explicit user id or by email (exactly one required)."""

    role: str
    user_id: str | None = None
    email: str | None = None

    @model_validator(mode="after")
    def check_target(self) -> InviteMemberRequest:
        if (self.user_id is None) == (self.email is None):
            msg = "Provide exactly one of user_id or email."
            raise ValueError(msg)
        return self


class TenantUserResponse(BaseModel):
    id: str
    tenant_id: str
    user_id: str
    role: str
    created_at: datetime


class MeRoleResponse(BaseModel):
    tenant_id: str
    user_id: str
    role: str
    permissions: list[str]


class MemberDetailsResponse(BaseModel):
    user_id: str
    email: str
    role: str
    created_at: datetime


class UpdateMemberRoleRequest(BaseModel):
    role: str = Field(..., description="OWNER, ACCOUNTANT, or VIEWER")
