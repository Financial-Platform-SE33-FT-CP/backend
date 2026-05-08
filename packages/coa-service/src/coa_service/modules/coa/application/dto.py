from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class CreateAccountRequest(BaseModel):
    code: str
    name: str
    account_type: str
    parent_code: Optional[str] = None
    description: Optional[str] = None


class UpdateAccountRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class AccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    code: str
    name: str
    account_type: str
    parent_id: Optional[str] = None
    is_active: bool
    is_system: bool
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class AccountTreeNode(BaseModel):
    id: str
    code: str
    name: str
    account_type: str
    children: list["AccountTreeNode"] = []
