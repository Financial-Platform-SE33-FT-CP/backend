"""Pydantic request/response schemas for the auth API."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterRequestSchema(BaseModel):
    """Request schema for user registration."""

    model_config = ConfigDict(from_attributes=True)

    email: str = Field(..., description="User email address")
    password: str = Field(
        ..., min_length=8, description="User password (min 8 characters)"
    )
    full_name: str | None = Field(None, description="User display name")


class LoginRequestSchema(BaseModel):
    """Request schema for user login."""

    model_config = ConfigDict(from_attributes=True)

    email: str = Field(..., description="User email address")
    password: str = Field(..., description="User password")


class TokenResponseSchema(BaseModel):
    """Response schema containing JWT tokens."""

    model_config = ConfigDict(from_attributes=True)

    access_token: str = Field(..., description="JWT access token")
    refresh_token: str = Field(..., description="JWT refresh token")
    token_type: str = Field(default="bearer", description="Token type")


class UserResponseSchema(BaseModel):
    """Response schema for user data."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="User unique identifier")
    email: str = Field(..., description="User email address")
    full_name: str | None = Field(None, description="User display name")
    email_verified: bool = Field(..., description="Whether email is verified")
    is_active: bool = Field(..., description="Whether account is active")
    created_at: datetime = Field(..., description="Account creation timestamp")


class ErrorResponseSchema(BaseModel):
    """Response schema for error responses."""

    model_config = ConfigDict(from_attributes=True)

    detail: str = Field(..., description="Error message")
    code: str | None = Field(None, description="Error code")
