"""User repository interface (abstract)."""

from abc import ABC, abstractmethod

from accounting_shared.types import UserId

from auth_service.modules.auth.domain.entities import User, VerificationToken


class UserRepository(ABC):
    """Abstract repository for user persistence operations."""

    @abstractmethod
    async def get_by_email(self, email: str) -> User | None:
        """Retrieve a user by email address."""
        ...

    @abstractmethod
    async def get_by_id(self, id: UserId) -> User | None:
        """Retrieve a user by their unique identifier."""
        ...

    @abstractmethod
    async def add(self, user: User) -> User:
        """Persist a new user."""
        ...

    @abstractmethod
    async def update(self, user: User) -> User:
        """Update an existing user."""
        ...

    @abstractmethod
    async def create_verification_token(
        self, user_id: UserId
    ) -> VerificationToken:
        """Create an email verification token for the given user."""
        ...

    @abstractmethod
    async def get_verification_token(
        self, token: str
    ) -> VerificationToken | None:
        """Retrieve a verification token by its value."""
        ...

    @abstractmethod
    async def mark_email_verified(self, user_id: UserId) -> None:
        """Mark a user's email as verified."""
        ...
