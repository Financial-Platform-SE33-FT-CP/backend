"""Orchestrate US-7 opening balance import."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from accounting_shared.exceptions import ValidationError

from ledger_service.modules.ledger.infrastructure.models import JournalEntryModel
from ledger_service.modules.ledger.infrastructure.repository import (
    SqlAlchemyJournalEntryRepository,
)
from ledger_service.modules.opening_balance.application.csv_parser import (
    parse_opening_balance_csv,
)
from ledger_service.modules.opening_balance.application.validator import (
    OpeningBalanceValidator,
)
from ledger_service.modules.opening_balance.domain.entities import (
    ParsedOpeningImport,
    ValidationIssue,
)
from ledger_service.modules.opening_balance.infrastructure.coa_lookup import (
    SqlAlchemyCoaAccountResolver,
)
from ledger_service.modules.opening_balance.infrastructure.subledger_writer import (
    OpeningSubledgerWriter,
)

OPENING_SOURCE_TYPE = "opening_balance"
DEFAULT_REVENUE_CODE = "4000"
DEFAULT_EXPENSE_CODE = "6900"


class OpeningBalanceService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._journal_repo = SqlAlchemyJournalEntryRepository(session)
        self._coa = SqlAlchemyCoaAccountResolver(session)
        self._validator = OpeningBalanceValidator(self._coa)
        self._subledger = OpeningSubledgerWriter(session)

    async def has_opening_balance(self, tenant_id: str) -> bool:
        stmt = select(JournalEntryModel.id).where(
            JournalEntryModel.tenant_id == tenant_id,
            JournalEntryModel.source_type == OPENING_SOURCE_TYPE,
        )
        result = await self._session.execute(stmt)
        return result.scalars().first() is not None

    def parse_csv(self, content: str | bytes) -> ParsedOpeningImport:
        return parse_opening_balance_csv(content)

    async def validate_import(
        self, tenant_id: str, parsed: ParsedOpeningImport
    ) -> tuple[dict, list[ValidationIssue]]:
        preview, _resolved, issues = await self._validator.validate(
            tenant_id,
            parsed,
            opening_already_posted=await self.has_opening_balance(tenant_id),
        )
        return {
            "valid": len(issues) == 0,
            "preview": {
                "total_debit": str(preview.total_debit),
                "total_credit": str(preview.total_credit),
                "trial_balance_line_count": preview.trial_balance_line_count,
                "ar_aging_line_count": preview.ar_aging_line_count,
                "ap_aging_line_count": preview.ap_aging_line_count,
                "ar_aging_total": str(preview.ar_aging_total),
                "ap_aging_total": str(preview.ap_aging_total),
            },
            "errors": [
                {"row": e.row, "field": e.field, "message": e.message} for e in issues
            ],
        }, issues

    async def import_opening_balance(
        self,
        *,
        tenant_id: str,
        parsed: ParsedOpeningImport,
        entry_date: date,
        created_by: str | None,
        reference: str = "OPENING",
    ) -> dict:
        preview, resolved_lines, issues = await self._validator.validate(
            tenant_id,
            parsed,
            opening_already_posted=await self.has_opening_balance(tenant_id),
        )
        self._validator.raise_if_issues(issues)

        lines_payload = [
            {
                "account_id": line.account_id,
                "debit_amount": line.debit,
                "credit_amount": line.credit,
                "description": line.description or f"Opening {line.account_code}",
            }
            for line in resolved_lines
        ]

        entry_id = await self._journal_repo.create_opening_entry(
            tenant_id=tenant_id,
            entry_date=entry_date,
            reference=reference,
            description="Opening trial balance import",
            source_type=OPENING_SOURCE_TYPE,
            created_by=created_by,
            lines=lines_payload,
        )

        revenue_id = preview.resolved_accounts.get(DEFAULT_REVENUE_CODE)
        if not revenue_id and parsed.ar_aging:
            extra = await self._coa.resolve_codes(tenant_id, {DEFAULT_REVENUE_CODE})
            revenue_id = extra.get(DEFAULT_REVENUE_CODE)
        if parsed.ar_aging and not revenue_id:
            raise ValidationError(
                f"Account code {DEFAULT_REVENUE_CODE} is required for AR invoice lines."
            )

        expense_id = preview.resolved_accounts.get(DEFAULT_EXPENSE_CODE)
        if not expense_id and parsed.ap_aging:
            extra = await self._coa.resolve_codes(tenant_id, {DEFAULT_EXPENSE_CODE})
            expense_id = extra.get(DEFAULT_EXPENSE_CODE)
        if parsed.ap_aging and not expense_id:
            raise ValidationError(
                f"Account code {DEFAULT_EXPENSE_CODE} is required for AP bill lines."
            )

        ar_count = await self._subledger.create_ar_aging(
            tenant_id=tenant_id,
            journal_entry_id=entry_id,
            lines=parsed.ar_aging,
            revenue_account_id=revenue_id or "",
        )
        ap_count = await self._subledger.create_ap_aging(
            tenant_id=tenant_id,
            journal_entry_id=entry_id,
            lines=parsed.ap_aging,
            expense_account_id=expense_id or "",
        )

        return {
            "journal_entry_id": entry_id,
            "reference": reference,
            "entry_date": entry_date.isoformat(),
            "line_count": len(lines_payload),
            "ar_documents_created": ar_count,
            "ap_documents_created": ap_count,
            "total_debit": str(preview.total_debit),
            "total_credit": str(preview.total_credit),
        }
