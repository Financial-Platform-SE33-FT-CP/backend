from __future__ import annotations

import pytest
from accounting_shared.exceptions import ValidationError

from ledger_service.modules.opening_balance.application.validator import (
    OpeningBalanceValidator,
)
from ledger_service.modules.opening_balance.domain.entities import ValidationIssue


class EmptyResolver:
    async def resolve_codes(self, tenant_id: str, codes: set[str]) -> dict[str, str]:
        return {}


def test_raise_if_issues_raises() -> None:
    validator = OpeningBalanceValidator(EmptyResolver())
    with pytest.raises(ValidationError, match="trial_balance"):
        validator.raise_if_issues(
            [ValidationIssue(row=None, field="trial_balance", message="not balanced")]
        )
