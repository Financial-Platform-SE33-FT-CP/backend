import enum
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from accounting_shared.database import Base


class AccountType(str, enum.Enum):
    ASSET = "asset"
    LIABILITY = "liability"
    EQUITY = "equity"
    REVENUE = "revenue"
    EXPENSE = "expense"


class AccountModel(Base):
    __tablename__ = "chart_of_accounts"

    id = Column(UUID(as_uuid=True), primary_key=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    code = Column(String(20), nullable=False)
    name = Column(String(255), nullable=False)
    account_type = Column(Enum(AccountType), nullable=False)
    parent_id = Column(
        UUID(as_uuid=True),
        ForeignKey("chart_of_accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    is_active = Column(Boolean, default=True, nullable=False)
    is_system = Column(Boolean, default=False, nullable=False)
    description = Column(String(500), nullable=True)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)

    parent = relationship(
        "AccountModel", remote_side="AccountModel.id", back_populates="children"
    )
    children = relationship(
        "AccountModel", back_populates="parent", passive_deletes=True
    )
