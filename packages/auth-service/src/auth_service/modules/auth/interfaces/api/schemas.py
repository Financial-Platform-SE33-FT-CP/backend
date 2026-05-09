"""Pydantic request/response schemas for the auth API."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class RegisterRequestSchema(BaseModel):
    """Request schema for user registration."""

    model_config = ConfigDict(from_attributes=True)

    email: EmailStr = Field(..., description="User email address")
    password: str = Field(..., min_length=8, description="Strong password")
    full_name: str | None = Field(None, description="Optional display name")

    @field_validator("password")
    @classmethod
    def password_strength(cls, value: str) -> str:
        if len(value) > 128:
            msg = "Password must not exceed 128 characters."
            raise ValueError(msg)
        if not any(c.isupper() for c in value):
            msg = "Password must contain at least one uppercase letter."
            raise ValueError(msg)
        if not any(c.islower() for c in value):
            msg = "Password must contain at least one lowercase letter."
            raise ValueError(msg)
        if not any(c.isdigit() for c in value):
            msg = "Password must contain at least one digit."
            raise ValueError(msg)
        return value


class LoginRequestSchema(BaseModel):
    """Request schema for user login."""

    model_config = ConfigDict(from_attributes=True)

    email: EmailStr = Field(..., description="User email address")
    password: str = Field(..., description="User password")


class VerifyEmailRequestSchema(BaseModel):
    """Request schema for email verification."""

    model_config = ConfigDict(from_attributes=True)

    token: str = Field(..., min_length=8, description="Opaque verification token")


class RefreshTokenRequestSchema(BaseModel):
    """Request schema for refresh and logout."""

    model_config = ConfigDict(from_attributes=True)

    refresh_token: str = Field(..., min_length=8)


class TokenResponseSchema(BaseModel):
    """Response schema containing JWT access token and metadata."""

    model_config = ConfigDict(from_attributes=True)

    access_token: str = Field(..., description="JWT access token")
    token_type: str = Field(default="bearer", description="Token type")
    expires_in: int = Field(
        ...,
        description="Access token lifetime in seconds from issuance",
    )
    refresh_token: str | None = Field(
        default=None,
        description="Opaque refresh token (present on login)",
    )
    refresh_expires_in: int | None = Field(
        default=None,
        description="Refresh token lifetime in seconds from issuance (login only)",
    )


class UserResponseSchema(BaseModel):
    """Response schema for registration (non-sensitive fields only)."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="User unique identifier")
    email: str = Field(..., description="User email address")
    full_name: str | None = Field(None, description="User display name")
    email_verified: bool = Field(..., description="Whether email is verified")
    is_active: bool = Field(..., description="Whether account is active")
    created_at: datetime = Field(..., description="Account creation timestamp")


class CurrentUserResponseSchema(BaseModel):
    """Minimal profile for GET /auth/me."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="User unique identifier")
    email: str = Field(..., description="User email address")
    email_verified: bool = Field(..., description="Whether email is verified")


class ErrorResponseSchema(BaseModel):
    """Response schema for error responses."""

    model_config = ConfigDict(from_attributes=True)

    detail: str = Field(..., description="Error message")
