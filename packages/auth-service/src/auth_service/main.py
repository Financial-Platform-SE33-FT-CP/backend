"""FastAPI application factory for the auth service."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from accounting_shared.database import create_session_factory
from accounting_shared.exceptions import register_exception_handlers
from accounting_shared.logging import setup_logging
from accounting_shared.middleware.request_id import RequestIDMiddleware
from accounting_shared.middleware.tenant_context import TenantContextMiddleware
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import create_async_engine

from auth_service.config import AuthSettings
from auth_service.deps import get_settings
from auth_service.modules.auth.domain.exceptions import VerificationEmailFailedError
from auth_service.modules.auth.interfaces.api.router import router as auth_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: setup and teardown resources."""
    settings: AuthSettings = get_settings()

    # Configure structured logging
    setup_logging(settings.log_level)

    # Create async engine and session factory
    engine_kwargs: dict[str, object] = {
        "pool_size": settings.database_pool_size,
        "max_overflow": settings.database_pool_overflow,
    }
    if settings.database_url.startswith("sqlite"):
        engine_kwargs["connect_args"] = {"check_same_thread": False}

    engine = create_async_engine(settings.database_url, **engine_kwargs)
    session_factory = create_session_factory(engine)

    # Store on app state for dependency injection
    app.state.session_factory = session_factory
    app.state.engine = engine

    yield

    # Teardown
    await engine.dispose()


def create_app() -> FastAPI:
    """Build and return the FastAPI application instance."""
    settings: AuthSettings = get_settings()

    app = FastAPI(
        title="Auth Service",
        description="Authentication and authorization service",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Middleware — order matters: outermost first
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(TenantContextMiddleware)

    # Register shared domain exception handlers
    register_exception_handlers(app)

    @app.exception_handler(VerificationEmailFailedError)
    async def verification_email_failed_handler(
        _request: Request,
        exc: VerificationEmailFailedError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )

    # Health check
    @app.get("/health")
    async def health_check() -> dict[str, str]:
        return {"status": "ok", "service": "auth-service"}

    # Include auth router
    app.include_router(auth_router, prefix="/auth")

    return app


app = create_app()
