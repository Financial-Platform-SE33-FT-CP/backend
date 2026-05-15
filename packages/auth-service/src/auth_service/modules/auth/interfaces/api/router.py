"""FastAPI router for auth endpoints."""

from fastapi import APIRouter, Depends, status

from auth_service.deps import (
    get_access_token_value,
    get_auth_service,
)
from auth_service.modules.auth.application.dto import (
    LoginRequest,
    RefreshTokenBody,
    RegisterRequest,
    ResendVerificationCodeRequest,
    VerifyEmailCodeRequest,
)
from auth_service.modules.auth.application.services import AuthService
from auth_service.modules.auth.interfaces.api.schemas import (
    CurrentUserResponseSchema,
    ErrorResponseSchema,
    LoginRequestSchema,
    MessageResponseSchema,
    RefreshTokenRequestSchema,
    RegisterAPIResponseSchema,
    RegisterRequestSchema,
    ResendVerificationCodeRequestSchema,
    TokenResponseSchema,
    VerifyEmailCodeRequestSchema,
)

router = APIRouter(tags=["auth"])


@router.post(
    "/register",
    response_model=RegisterAPIResponseSchema,
    response_model_exclude_none=True,
    status_code=status.HTTP_201_CREATED,
    responses={
        409: {"model": ErrorResponseSchema, "description": "Email already exists"},
        422: {"model": ErrorResponseSchema, "description": "Validation error"},
        503: {"model": ErrorResponseSchema, "description": "Verification email failed to send"},
    },
)
async def register(
    body: RegisterRequestSchema,
    auth_service: AuthService = Depends(get_auth_service),
) -> RegisterAPIResponseSchema:
    """Register a new user account."""
    dto = RegisterRequest(
        email=body.email,
        password=body.password,
        full_name=body.full_name,
    )
    result = await auth_service.register(dto)
    u = result.user
    return RegisterAPIResponseSchema(
        id=u.id,
        email=u.email,
        full_name=u.full_name,
        email_verified=u.is_email_verified,
        is_active=u.is_active,
        created_at=u.created_at,
        message=result.message,
        verification_code=result.verification_code,
    )


@router.post(
    "/login",
    response_model=TokenResponseSchema,
    responses={
        401: {"model": ErrorResponseSchema, "description": "Authentication failed"},
        422: {"model": ErrorResponseSchema, "description": "Validation error"},
    },
)
async def login(
    body: LoginRequestSchema,
    auth_service: AuthService = Depends(get_auth_service),
) -> TokenResponseSchema:
    """Authenticate a user and return tokens."""
    dto = LoginRequest(email=body.email, password=body.password)
    result = await auth_service.login(dto)
    return TokenResponseSchema(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        token_type=result.token_type,
        expires_in=result.expires_in,
        refresh_expires_in=result.refresh_expires_in,
    )


@router.post(
    "/verify-email-code",
    response_model=MessageResponseSchema,
    responses={
        401: {"model": ErrorResponseSchema, "description": "Invalid or expired code"},
        422: {"model": ErrorResponseSchema, "description": "Validation error"},
    },
)
async def verify_email_code(
    body: VerifyEmailCodeRequestSchema,
    auth_service: AuthService = Depends(get_auth_service),
) -> MessageResponseSchema:
    """Verify email using the numeric code from email."""
    dto = VerifyEmailCodeRequest(email=body.email, code=body.code)
    msg = await auth_service.verify_email_with_code(str(dto.email), dto.code)
    return MessageResponseSchema(message=msg)


@router.post(
    "/resend-verification-code",
    response_model=MessageResponseSchema,
    responses={
        422: {"model": ErrorResponseSchema, "description": "Validation error"},
    },
)
async def resend_verification_code(
    body: ResendVerificationCodeRequestSchema,
    auth_service: AuthService = Depends(get_auth_service),
) -> MessageResponseSchema:
    """Resend verification code (generic response; anti-enumeration)."""
    dto = ResendVerificationCodeRequest(email=body.email)
    msg = await auth_service.resend_verification_code(str(dto.email))
    return MessageResponseSchema(message=msg)


@router.post(
    "/refresh",
    response_model=TokenResponseSchema,
    response_model_exclude_none=True,
    responses={
        401: {"model": ErrorResponseSchema, "description": "Invalid refresh token"},
        422: {"model": ErrorResponseSchema, "description": "Validation error"},
    },
)
async def refresh_tokens(
    body: RefreshTokenRequestSchema,
    auth_service: AuthService = Depends(get_auth_service),
) -> TokenResponseSchema:
    """Issue a new access token using a refresh token."""
    payload = RefreshTokenBody(refresh_token=body.refresh_token)
    result = await auth_service.refresh_access_token(payload.refresh_token)
    return TokenResponseSchema(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        token_type=result.token_type,
        expires_in=result.expires_in,
        refresh_expires_in=result.refresh_expires_in,
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        422: {"model": ErrorResponseSchema, "description": "Validation error"},
    },
)
async def logout(
    body: RefreshTokenRequestSchema,
    auth_service: AuthService = Depends(get_auth_service),
) -> None:
    """Revoke a refresh token."""
    payload = RefreshTokenBody(refresh_token=body.refresh_token)
    await auth_service.logout(payload.refresh_token)


@router.get(
    "/me",
    response_model=CurrentUserResponseSchema,
    responses={
        401: {"model": ErrorResponseSchema, "description": "Invalid or missing token"},
    },
)
async def get_me(
    access_token: str = Depends(get_access_token_value),
    auth_service: AuthService = Depends(get_auth_service),
) -> CurrentUserResponseSchema:
    """Return the current authenticated user's profile."""
    result = await auth_service.get_current_user(access_token)
    return CurrentUserResponseSchema(
        id=result.id,
        email=result.email,
        email_verified=result.email_verified,
    )


@router.get(
    "/verify",
    response_model=dict,
    responses={
        401: {"model": ErrorResponseSchema, "description": "Invalid token"},
    },
)
async def verify_token(
    access_token: str = Depends(get_access_token_value),
    auth_service: AuthService = Depends(get_auth_service),
) -> dict:
    """Validate a JWT token for other services (inter-service auth)."""
    user = await auth_service.verify_access_token_for_gateway(access_token)
    return {
        "valid": True,
        "user_id": user.id,
        "email": user.email,
        "email_verified": user.email_verified,
    }
