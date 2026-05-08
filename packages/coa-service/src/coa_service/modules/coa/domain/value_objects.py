from dataclasses import dataclass


@dataclass(frozen=True)
class AccountCode:
    value: str

    def __post_init__(self) -> None:
        if not self.value or not self.value.strip():
            raise ValueError("Account code cannot be empty")
        if not self.value.isdigit():
            raise ValueError("Account code must be numeric")

    def __str__(self) -> str:
        return self.value
