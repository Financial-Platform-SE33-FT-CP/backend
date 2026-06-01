"""Validation for opening balance import (US-7)."""

from __future__ import annotations

from decimal import Decimal

from accounting_shared.exceptions import ValidationError

from ledger_service.modules.opening_balance.domain.entities import (
    OpeningImportPreview,
    ParsedOpeningImport,
    ResolvedTrialLine,
    ValidationIssue,
)

DEFAULT_AR_ACCOUNT_CODE = "1100"
DEFAULT_AP_ACCOUNT_CODE = "2000"
BALANCE_TOLERANCE = Decimal("0.01")


class CoaAccountResolver:
    """Resolve account codes to IDs for a tenant."""

    async def resolve_codes(
        self, tenant_id: str, codes: set[str]
    ) -> dict[str, str]:
        raise NotImplementedError


class OpeningBalanceValidator:
    """Validate parsed CSV before posting."""

    def __init__(
        self,
        coa_resolver: CoaAccountResolver,
        *,
        ar_control_code: str = DEFAULT_AR_ACCOUNT_CODE,
        ap_control_code: str = DEFAULT_AP_ACCOUNT_CODE,
    ) -> None:
        self._coa = coa_resolver
        self._ar_code = ar_control_code
        self._ap_code = ap_control_code

    async def validate(
        self,
        tenant_id: str,
        parsed: ParsedOpeningImport,
        *,
        opening_already_posted: bool = False,
    ) -> tuple[OpeningImportPreview, list[ResolvedTrialLine], list[ValidationIssue]]:
        issues: list[ValidationIssue] = []

        if opening_already_posted:
            issues.append(
                ValidationIssue(
                    row=None,
                    field="tenant",
                    message="Opening balance has already been imported for this company.",
                )
            )

        codes = {line.account_code for line in parsed.trial_balance}
        resolved_map = await self._coa.resolve_codes(tenant_id, codes)
        for line in parsed.trial_balance:
            if line.account_code not in resolved_map:
                issues.append(
                    ValidationIssue(
                        row=line.row_number,
                        field="account_code",
                        message=f"Unknown or inactive account code '{line.account_code}'.",
                    )
                )

        total_debit = sum((line.debit for line in parsed.trial_balance), Decimal("0"))
        total_credit = sum((line.credit for line in parsed.trial_balance), Decimal("0"))
        if abs(total_debit - total_credit) > BALANCE_TOLERANCE:
            issues.append(
                ValidationIssue(
                    row=None,
                    field="trial_balance",
                    message=(
                        f"Trial balance does not balance: debits {total_debit} "
                        f"≠ credits {total_credit}."
                    ),
                )
            )

        ar_total = sum((line.amount for line in parsed.ar_aging), Decimal("0"))
        ap_total = sum((line.amount for line in parsed.ap_aging), Decimal("0"))

        ar_control_debit = Decimal("0")
        for line in parsed.trial_balance:
            if line.account_code == self._ar_code:
                ar_control_debit += line.debit - line.credit

        ap_control_credit = Decimal("0")
        for line in parsed.trial_balance:
            if line.account_code == self._ap_code:
                ap_control_credit += line.credit - line.debit

        if parsed.ar_aging and ar_total != ar_control_debit:
            issues.append(
                ValidationIssue(
                    row=None,
                    field="ar_aging",
                    message=(
                        f"AR aging total {ar_total} must match net debit on account "
                        f"{self._ar_code} ({ar_control_debit})."
                    ),
                )
            )

        if parsed.ap_aging and ap_total != ap_control_credit:
            issues.append(
                ValidationIssue(
                    row=None,
                    field="ap_aging",
                    message=(
                        f"AP aging total {ap_total} must match net credit on account "
                        f"{self._ap_code} ({ap_control_credit})."
                    ),
                )
            )

        refs_ar = [line.reference for line in parsed.ar_aging]
        if len(refs_ar) != len(set(refs_ar)):
            issues.append(
                ValidationIssue(
                    row=None,
                    field="reference",
                    message="Duplicate reference in ar_aging section.",
                )
            )

        refs_ap = [line.reference for line in parsed.ap_aging]
        if len(refs_ap) != len(set(refs_ap)):
            issues.append(
                ValidationIssue(
                    row=None,
                    field="reference",
                    message="Duplicate reference in ap_aging section.",
                )
            )

        resolved_lines: list[ResolvedTrialLine] = []
        for line in parsed.trial_balance:
            account_id = resolved_map.get(line.account_code)
            if account_id:
                resolved_lines.append(
                    ResolvedTrialLine(
                        account_id=account_id,
                        account_code=line.account_code,
                        debit=line.debit,
                        credit=line.credit,
                        description=line.description,
                    )
                )

        preview = OpeningImportPreview(
            total_debit=total_debit,
            total_credit=total_credit,
            trial_balance_line_count=len(parsed.trial_balance),
            ar_aging_line_count=len(parsed.ar_aging),
            ap_aging_line_count=len(parsed.ap_aging),
            ar_aging_total=ar_total,
            ap_aging_total=ap_total,
            resolved_accounts=dict(resolved_map),
        )

        return preview, resolved_lines, issues

    def raise_if_issues(self, issues: list[ValidationIssue]) -> None:
        if not issues:
            return
        detail = "; ".join(
            (
                f"Row {i.row}: {i.message}"
                if i.row is not None
                else f"{i.field}: {i.message}"
            )
            for i in issues
        )
        raise ValidationError(detail)
