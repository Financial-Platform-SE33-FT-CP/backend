"""Application-layer DTOs for the auth module."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class RegisterRequest(BaseModel):
    """DTO for user registration request."""

    model_config = ConfigDict(from_attributes=True)

    email: str
    password: str
    full_name: str | None = None


class LoginRequest(BaseModel):
    """DTO for login request."""

    model_config = ConfigDict(from_attributes=True)

    email: str
    password: str


class TokenResponse(BaseModel):
    """DTO for token response."""

    model_config = ConfigDict(from_attributes=True)

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class VerifyEmailRequest(BaseModel):
    """DTO for email verification request."""

    model_config = ConfigDict(from_attributes=True)

    token: str


class UserResponse(BaseModel):
    """DTO for user response data."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    full_name: str | None
    email_verified: bool
    is_active: bool
    created_at: datetime
