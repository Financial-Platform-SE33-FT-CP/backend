from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CreateAccountRequest(BaseModel):
    code: str
    name: str
    account_type: str
    parent_code: str | None = None
    description: str | None = None


class UpdateAccountRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    is_active: bool | None = None


class AccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    code: str
    name: str
    account_type: str
    parent_id: str | None = None
    is_active: bool
    is_system: bool
    description: str | None = None
    created_at: datetime
    updated_at: datetime

    @field_validator("id", "tenant_id", "parent_id", mode="before")
    @classmethod
    def _uuid_fields_to_str(cls, value: object) -> str | None:
        if value is None:
            return None
        if isinstance(value, UUID):
            return str(value)
        return str(value)


class AccountTreeNode(BaseModel):
    id: str
    code: str
    name: str
    account_type: str
    children: list["AccountTreeNode"] = Field(default_factory=list)
