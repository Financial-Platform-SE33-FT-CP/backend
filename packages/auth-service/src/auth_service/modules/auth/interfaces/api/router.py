"""FastAPI router for auth endpoints."""

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status

from accounting_shared.middleware.tenant_context import get_current_tenant_id

from auth_service.deps import get_async_session, get_auth_service, get_settings
from auth_service.config import AuthSettings
from auth_service.modules.auth.application.dto import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    VerifyEmailRequest,
)
from auth_service.modules.auth.application.services import AuthService
from auth_service.modules.auth.interfaces.api.schemas import (
    ErrorResponseSchema,
    LoginRequestSchema,
    RegisterRequestSchema,
    TokenResponseSchema,
    UserResponseSchema,
)

router = APIRouter(tags=["auth"])


@router.post(
    "/register",
    response_model=UserResponseSchema,
    status_code=status.HTTP_201_CREATED,
    responses={
        409: {"model": ErrorResponseSchema, "description": "Email already exists"},
        422: {"model": ErrorResponseSchema, "description": "Validation error"},
    },
)
async def register(
    body: RegisterRequestSchema,
    session: AsyncSession = Depends(get_async_session),
) -> UserResponseSchema:
    """Register a new user account."""
    auth_service = await get_auth_service(session)
    dto = RegisterRequest(
        email=body.email,
        password=body.password,
        full_name=body.full_name,
    )
    result = await auth_service.register(dto)
    return UserResponseSchema(
        id=result.id,
        email=result.email,
        full_name=result.full_name,
        email_verified=result.email_verified,
        is_active=result.is_active,
        created_at=result.created_at,
    )


@router.post(
    "/login",
    response_model=TokenResponseSchema,
    responses={
        401: {"model": ErrorResponseSchema, "description": "Invalid credentials"},
        403: {"model": ErrorResponseSchema, "description": "Account locked or email not verified"},
    },
)
async def login(
    body: LoginRequestSchema,
    session: AsyncSession = Depends(get_async_session),
) -> TokenResponseSchema:
    """Authenticate a user and return JWT tokens."""
    auth_service = await get_auth_service(session)
    dto = LoginRequest(email=body.email, password=body.password)
    result = await auth_service.login(dto)
    return TokenResponseSchema(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        token_type=result.token_type,
    )


@router.post(
    "/verify-email",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        400: {"model": ErrorResponseSchema, "description": "Invalid or expired token"},
    },
)
async def verify_email(
    body: VerifyEmailRequest,
    session: AsyncSession = Depends(get_async_session),
) -> None:
    """Verify a user's email address using a verification token."""
    auth_service = await get_auth_service(session)
    await auth_service.verify_email(body.token)


@router.post(
    "/refresh",
    response_model=TokenResponseSchema,
    responses={
        401: {"model": ErrorResponseSchema, "description": "Invalid refresh token"},
    },
)
async def refresh(
    refresh_token: str = Header(..., alias="X-Refresh-Token"),
    session: AsyncSession = Depends(get_async_session),
) -> TokenResponseSchema:
    """Issue a new access token using a refresh token."""
    # Support both header and body approach — header is preferred
    auth_service = await get_auth_service(session)
    result = await auth_service.refresh_token(refresh_token)
    return TokenResponseSchema(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        token_type=result.token_type,
    )


@router.get(
    "/me",
    response_model=UserResponseSchema,
    responses={
        401: {"model": ErrorResponseSchema, "description": "Invalid or missing token"},
    },
)
async def get_me(
    authorization: str = Header(..., alias="Authorization"),
    session: AsyncSession = Depends(get_async_session),
) -> UserResponseSchema:
    """Return the current authenticated user's profile."""
    # Extract Bearer token
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header format.",
        )
    token = authorization.removeprefix("Bearer ")

    auth_service = await get_auth_service(session)
    result = await auth_service.get_current_user(token)
    return UserResponseSchema(
        id=result.id,
        email=result.email,
        full_name=result.full_name,
        email_verified=result.email_verified,
        is_active=result.is_active,
        created_at=result.created_at,
    )


@router.get(
    "/verify",
    response_model=dict,
    responses={
        401: {"model": ErrorResponseSchema, "description": "Invalid token"},
    },
)
async def verify_token(
    authorization: str = Header(..., alias="Authorization"),
    session: AsyncSession = Depends(get_async_session),
) -> dict:
    """Validate a JWT token for other services (inter-service auth)."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header format.",
        )
    token = authorization.removeprefix("Bearer ")

    auth_service = await get_auth_service(session)
    user = await auth_service.get_current_user(token)
    return {
        "valid": True,
        "user_id": user.id,
        "email": user.email,
    }
