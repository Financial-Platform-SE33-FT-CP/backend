"""Application-layer DTOs for the auth module."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr


class RegisterRequest(BaseModel):
    """DTO for user registration request."""

    model_config = ConfigDict(from_attributes=True)

    email: EmailStr
    password: str
    full_name: str | None = None


class LoginRequest(BaseModel):
    """DTO for login request."""

    model_config = ConfigDict(from_attributes=True)

    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """DTO for token response."""

    model_config = ConfigDict(from_attributes=True)

    access_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_token: str | None = None
    refresh_expires_in: int | None = None


class VerifyEmailCodeRequest(BaseModel):
    """DTO for email verification with numeric code."""

    model_config = ConfigDict(from_attributes=True)

    email: EmailStr
    code: str


class ResendVerificationCodeRequest(BaseModel):
    """DTO for resending verification code."""

    model_config = ConfigDict(from_attributes=True)

    email: EmailStr


class RefreshTokenBody(BaseModel):
    """DTO for refresh / logout body."""

    model_config = ConfigDict(from_attributes=True)

    refresh_token: str


class CurrentUserResponse(BaseModel):
    """Minimal profile for GET /auth/me."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    email_verified: bool


class UserResponse(BaseModel):
    """DTO for full user response data (e.g. registration)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    full_name: str | None
    email_verified: bool
    is_active: bool
    created_at: datetime


class RegisterUserSnippet(BaseModel):
    """Safe user fields returned from registration."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    full_name: str | None = None
    is_email_verified: bool


class RegisterResponse(BaseModel):
    """Registration API response (no secrets)."""

    model_config = ConfigDict(from_attributes=True)

    message: str
    user: RegisterUserSnippet
    verification_code: str | None = None
