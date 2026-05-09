"""Auth domain-specific exceptions."""

from accounting_shared.exceptions import (
    ConflictError,
    UnauthorizedError,
)


class InvalidCredentialsError(UnauthorizedError):
    """Login credentials do not match any known account."""

    def __init__(self, message: str = "Invalid email or password.") -> None:
        super().__init__(detail=message)


class EmailAlreadyExistsError(ConflictError):
    """An account with this email already exists."""

    def __init__(
        self,
        message: str = "An account with this email already exists.",
    ) -> None:
        super().__init__(detail=message)


class EmailNotVerifiedError(UnauthorizedError):
    """The email address has not been verified."""

    def __init__(
        self,
        message: str = "Email address has not been verified.",
    ) -> None:
        super().__init__(detail=message)


class AccountLockedError(UnauthorizedError):
    """The account is temporarily locked due to too many failed attempts."""

    def __init__(
        self,
        message: str = ("Account is temporarily locked due to too many failed login attempts."),
    ) -> None:
        super().__init__(detail=message)


class InvalidTokenError(UnauthorizedError):
    """The provided token is invalid or expired."""

    def __init__(self, message: str = "Invalid or expired token.") -> None:
        super().__init__(detail=message)
