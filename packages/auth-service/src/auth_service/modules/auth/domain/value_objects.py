"""Auth domain value objects."""

import re
from dataclasses import dataclass

from accounting_shared.exceptions import ValidationError

_EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


@dataclass(frozen=True)
class Email:
    """Email value object with validation."""

    value: str

    def __post_init__(self) -> None:
        if not self.value or not isinstance(self.value, str):
            raise ValidationError("Email must be a non-empty string.")
        if not _EMAIL_PATTERN.match(self.value):
            raise ValidationError(f"Invalid email format: {self.value!r}")
        if len(self.value) > 254:
            raise ValidationError("Email must not exceed 254 characters.")

    def __str__(self) -> str:
        return self.value
