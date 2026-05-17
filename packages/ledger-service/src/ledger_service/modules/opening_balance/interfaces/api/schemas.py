"""API schemas for opening balance import (US-7)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ValidationErrorItem(BaseModel):
    row: int | None = None
    field: str
    message: str


class OpeningImportPreviewSchema(BaseModel):
    total_debit: str
    total_credit: str
    trial_balance_line_count: int
    ar_aging_line_count: int
    ap_aging_line_count: int
    ar_aging_total: str
    ap_aging_total: str


class OpeningValidateResponse(BaseModel):
    valid: bool
    preview: OpeningImportPreviewSchema | None = None
    errors: list[ValidationErrorItem] = Field(default_factory=list)


class OpeningImportResponse(BaseModel):
    journal_entry_id: str
    reference: str
    entry_date: str
    line_count: int
    ar_documents_created: int
    ap_documents_created: int
    total_debit: str
    total_credit: str
