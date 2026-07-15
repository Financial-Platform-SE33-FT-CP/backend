"""Bank statement CSV parser (US-13).

Supports standard CSV layouts with auto-detected headers.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from accounting_shared.exceptions import ValidationError
from ar_ap_service.modules.ar_ap.application.dto import UploadBankStatementCommand
from ar_ap_service.modules.ar_ap.domain.entities import BankTransaction
from ar_ap_service.modules.ar_ap.domain.repository import BankTransactionRepository


def _parse_date(raw: str) -> str:
    cleaned = raw.strip()
    m = re.match(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$", cleaned)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", cleaned)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    raise ValidationError(f"Unrecognized date format: {raw}")


def _clean_amount(raw: str) -> Decimal:
    cleaned = raw.strip().strip('"').strip("'")
    if not cleaned:
        return Decimal("0")
    cleaned = cleaned.replace(",", "")
    cleaned = re.sub(r"[^\d.\-]", "", cleaned)
    if not cleaned:
        return Decimal("0")
    return Decimal(cleaned)


def _compute_checksum(date_str: str, description: str, amount: str) -> str:
    normalized = f"{date_str}|{description.strip().lower()}|{amount.strip()}"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class DetectedLayout:
    """Describes how columns map to the canonical fields."""

    __slots__ = ("date_col", "desc_col", "amount_col", "debit_col", "credit_col")

    def __init__(
        self,
        date_col: int,
        desc_col: int,
        amount_col: int | None = None,
        debit_col: int | None = None,
        credit_col: int | None = None,
    ) -> None:
        self.date_col = date_col
        self.desc_col = desc_col
        self.amount_col = amount_col
        self.debit_col = debit_col
        self.credit_col = credit_col

    @property
    def is_credit_debit(self) -> bool:
        return self.debit_col is not None and self.credit_col is not None


def _detect_layout(headers: list[str]) -> DetectedLayout:
    lower = [h.strip().lower() for h in headers]
    date_idx: int | None = None
    desc_idx: int | None = None
    amount_idx: int | None = None
    debit_idx: int | None = None
    credit_idx: int | None = None

    for i, h in enumerate(lower):
        # Normalize: replace spaces with underscores for matching
        h_norm = h.replace(" ", "_")
        if h_norm in ("date", "transaction_date", "trans_date", "posting_date"):
            date_idx = i
        elif h_norm in (
            "description",
            "narration",
            "details",
            "memo",
            "particulars",
            "transaction_description",
        ):
            desc_idx = i
        elif h_norm in ("amount", "transaction_amount", "trx_amount", "value"):
            amount_idx = i
        elif h_norm in ("debit", "withdrawal", "dr", "withdrawals"):
            debit_idx = i
        elif h_norm in ("credit", "deposit", "cr", "deposits"):
            credit_idx = i

    if date_idx is not None and desc_idx is not None:
        if debit_idx is not None and credit_idx is not None:
            return DetectedLayout(date_idx, desc_idx, debit_col=debit_idx, credit_col=credit_idx)
        if amount_idx is not None:
            return DetectedLayout(date_idx, desc_idx, amount_col=amount_idx)

    if len(headers) >= 3:
        return DetectedLayout(0, 1, amount_col=2)

    raise ValidationError(
        "Could not detect CSV layout. "
        "Expected columns: date, description, amount (or debit/credit pair). "
        f"Got: {', '.join(headers)}"
    )


class ParsedTransaction:
    __slots__ = ("date", "description", "amount", "checksum_hash")

    def __init__(self, date: str, description: str, amount: Decimal, checksum_hash: str) -> None:
        self.date = date
        self.description = description
        self.amount = amount
        self.checksum_hash = checksum_hash


def parse_bank_statement_csv(content: str) -> list[ParsedTransaction]:
    reader = csv.reader(io.StringIO(content))
    rows: list[list[str]] = []
    for row in reader:
        cleaned = [c.strip() for c in row if c.strip()]
        if cleaned:
            rows.append(row)

    if len(rows) < 2:
        raise ValidationError("CSV must contain a header row and at least one data row")

    headers = rows[0]
    layout = _detect_layout(headers)

    transactions: list[ParsedTransaction] = []
    errors: list[str] = []

    for idx, row in enumerate(rows[1:], start=2):
        try:
            if layout.is_credit_debit:
                assert layout.debit_col is not None and layout.credit_col is not None
                raw_debit = row[layout.debit_col] if len(row) > layout.debit_col else ""
                raw_credit = row[layout.credit_col] if len(row) > layout.credit_col else ""
                debit_val = _clean_amount(raw_debit)
                credit_val = _clean_amount(raw_credit)
                amount_val = credit_val - debit_val
                raw_amount = str(amount_val) if amount_val != Decimal("0") else "0"
            else:
                if layout.amount_col is None or layout.amount_col >= len(row):
                    raise ValidationError(f"Missing amount column at row {idx}")
                raw_amount = row[layout.amount_col]

            date_str = _parse_date(row[layout.date_col])
            desc = row[layout.desc_col] if layout.desc_col < len(row) else ""
            amount = _clean_amount(raw_amount)
            checksum = _compute_checksum(date_str, desc, raw_amount)

            transactions.append(
                ParsedTransaction(
                    date=date_str,
                    description=desc,
                    amount=amount,
                    checksum_hash=checksum,
                )
            )
        except ValidationError:
            raise
        except Exception as exc:
            errors.append(f"Row {idx}: {exc}")

    if errors and not transactions:
        raise ValidationError(f"Failed to parse any rows: {'; '.join(errors[:3])}")

    return transactions


class BankStatementService:
    """Handles CSV bank statement uploads (US-13)."""

    def __init__(self, bank_txn_repo: BankTransactionRepository) -> None:
        self._bank_txn_repo = bank_txn_repo

    async def upload_statement(
        self,
        tenant_id: UUID,
        command: UploadBankStatementCommand,
    ) -> list[BankTransaction]:
        parsed = parse_bank_statement_csv(command.csv_content)
        batch_id = uuid4()
        created: list[BankTransaction] = []

        for pt in parsed:
            is_dup = await self._bank_txn_repo.exists_by_hash(tenant_id, pt.checksum_hash)
            if is_dup:
                continue
            txn = BankTransaction(
                id=uuid4(),
                tenant_id=tenant_id,
                bank_account_id=command.bank_account_id,
                transaction_date=date.fromisoformat(pt.date),
                description=pt.description,
                amount=pt.amount,
                matched=False,
                checksum_hash=pt.checksum_hash,
                upload_batch_id=batch_id,
                created_at=datetime.utcnow(),
            )
            created.append(txn)

        if not created:
            return []
        return await self._bank_txn_repo.add_many(tenant_id, created)
