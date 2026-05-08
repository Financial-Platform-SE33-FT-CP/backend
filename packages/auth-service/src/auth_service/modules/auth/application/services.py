"""Auth application services."""

from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

from accounting_shared.exceptions import NotFoundError
from accounting_shared.types import UserId, new_user_id

from auth_service.config import AuthSettings
from auth_service.modules.auth.domain.entities import User
from auth_service.modules.auth.domain.exceptions import (
    AccountLockedError,
    EmailAlreadyExistsError,
    EmailNotVerifiedError,
    InvalidCredentialsError,
    InvalidTokenError,
)
from auth_service.modules.auth.domain.repository import UserRepository
from auth_service.modules.auth.domain.value_objects import Email

from auth_service.modules.auth.application.dto import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)


class AuthService:
    """Application service for authentication operations."""

    def __init__(
        self,
        settings: AuthSettings,
        user_repository: UserRepository,
    ) -> None:
        self._settings = settings
        self._user_repo = user_repository

    @staticmethod
    def _hash_password(password: str, rounds: int = 12) -> str:
        """Hash a plain-text password using bcrypt."""
        salt = bcrypt.gensalt(rounds=rounds)
        return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

    @staticmethod
    def _verify_password(plain: str, hashed: str) -> bool:
        """Verify a plain-text password against a bcrypt hash."""
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))

    def _create_access_token(
        self, user_id: str, tenant_id: str | None = None
    ) -> str:
        """Create a JWT access token."""
        now = datetime.now(timezone.utc)
        expire = now + timedelta(
            minutes=self._settings.jwt_access_token_expire_minutes
        )
        payload: dict[str, object] = {
            "sub": user_id,
            "exp": expire,
            "iat": now,
            "type": "access",
        }
        if tenant_id:
            payload["tenant_id"] = tenant_id
        return jwt.encode(
            payload,
            self._settings.jwt_secret,
            algorithm=self._settings.jwt_algorithm,
        )

    def _create_refresh_token(self, user_id: str) -> str:
        """Create a JWT refresh token."""
        now = datetime.now(timezone.utc)
        expire = now + timedelta(
            days=self._settings.jwt_refresh_token_expire_days
        )
        payload: dict[str, object] = {
            "sub": user_id,
            "exp": expire,
            "iat": now,
            "type": "refresh",
        }
        return jwt.encode(
            payload,
            self._settings.jwt_secret,
            algorithm=self._settings.jwt_algorithm,
        )

    def _decode_token(self, token: str) -> dict[str, object]:
        """Decode and validate a JWT token."""
        try:
            payload = jwt.decode(
                token,
                self._settings.jwt_secret,
                algorithms=[self._settings.jwt_algorithm],
            )
        except JWTError as exc:
            raise InvalidTokenError("Token is invalid or expired.") from exc
        return payload

    async def register(self, dto: RegisterRequest) -> UserResponse:
        """Register a new user account."""
        # Validate email
        email = Email(dto.email)

        # Check for existing user
        existing = await self._user_repo.get_by_email(email.value)
        if existing is not None:
            raise EmailAlreadyExistsError()

        # Hash the password
        hashed = self._hash_password(
            dto.password, self._settings.bcrypt_rounds
        )

        # Create the user entity
        user_id = new_user_id()
        now = datetime.now(timezone.utc)
        user = User(
            id=user_id,
            email=email.value,
            hashed_password=hashed,
            full_name=dto.full_name,
            email_verified=not self._settings.email_verification_required,
            is_active=True,
            created_at=now,
            updated_at=now,
        )

        persisted = await self._user_repo.add(user)

        # Create verification token if required
        if self._settings.email_verification_required:
            await self._user_repo.create_verification_token(persisted.id)

        return self._user_to_response(persisted)

    async def login(self, dto: LoginRequest) -> TokenResponse:
        """Authenticate a user and return tokens."""
        email = Email(dto.email)

        user = await self._user_repo.get_by_email(email.value)
        if user is None:
            raise InvalidCredentialsError()

        # Verify password
        if not self._verify_password(dto.password, user.hashed_password):
            raise InvalidCredentialsError()

        # Check if account is active
        if not user.is_active:
            raise AccountLockedError()

        # Check email verification
        if (
            self._settings.email_verification_required
            and not user.email_verified
        ):
            raise EmailNotVerifiedError()

        access_token = self._create_access_token(str(user.id))
        refresh_token = self._create_refresh_token(str(user.id))

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
        )

    async def verify_email(self, token: str) -> None:
        """Verify a user's email using a verification token."""
        verification = await self._user_repo.get_verification_token(token)
        if verification is None:
            raise InvalidTokenError("Verification token not found.")

        if verification.expires_at < datetime.now(timezone.utc):
            raise InvalidTokenError("Verification token has expired.")

        await self._user_repo.mark_email_verified(verification.user_id)

    async def refresh_token(
        self, refresh_token: str
    ) -> TokenResponse:
        """Issue a new access token using a valid refresh token."""
        payload = self._decode_token(refresh_token)

        if payload.get("type") != "refresh":
            raise InvalidTokenError("Token is not a refresh token.")

        user_id_str = payload.get("sub")
        if user_id_str is None or not isinstance(user_id_str, str):
            raise InvalidTokenError("Token missing subject claim.")

        # Verify the user still exists
        user = await self._user_repo.get_by_id(UserId(user_id_str))
        if user is None:
            raise NotFoundError("User not found.")

        if not user.is_active:
            raise AccountLockedError()

        new_access = self._create_access_token(user_id_str)
        new_refresh = self._create_refresh_token(user_id_str)

        return TokenResponse(
            access_token=new_access,
            refresh_token=new_refresh,
        )

    async def get_current_user(self, token: str) -> UserResponse:
        """Return the current user from a valid access token."""
        payload = self._decode_token(token)

        if payload.get("type") != "access":
            raise InvalidTokenError("Token is not an access token.")

        user_id_str = payload.get("sub")
        if user_id_str is None or not isinstance(user_id_str, str):
            raise InvalidTokenError("Token missing subject claim.")

        user = await self._user_repo.get_by_id(UserId(user_id_str))
        if user is None:
            raise NotFoundError("User not found.")

        if not user.is_active:
            raise AccountLockedError()

        return self._user_to_response(user)

    def _user_to_response(self, user: User) -> UserResponse:
        """Convert a User entity to a UserResponse DTO."""
        return UserResponse(
            id=str(user.id),
            email=user.email,
            full_name=user.full_name,
            email_verified=user.email_verified,
            is_active=user.is_active,
            created_at=user.created_at,
        )
