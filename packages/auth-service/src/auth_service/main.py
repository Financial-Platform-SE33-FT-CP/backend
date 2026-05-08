"""FastAPI application factory for the auth service."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import create_async_engine

from accounting_shared.database import create_session_factory
from accounting_shared.exceptions import register_exception_handlers
from accounting_shared.logging import setup_logging
from accounting_shared.middleware.request_id import RequestIDMiddleware
from accounting_shared.middleware.tenant_context import TenantContextMiddleware

from auth_service.config import AuthSettings
from auth_service.deps import get_settings
from auth_service.modules.auth.interfaces.api.router import router as auth_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: setup and teardown resources."""
    settings: AuthSettings = get_settings()

    # Configure structured logging
    setup_logging(settings.log_level)

    # Create async engine and session factory
    engine = create_async_engine(
        settings.database_url,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_pool_overflow,
    )
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

    # Health check
    @app.get("/health")
    async def health_check() -> dict[str, str]:
        return {"status": "ok", "service": "auth-service"}

    # Include auth router
    app.include_router(auth_router, prefix="/auth")

    return app


app = create_app()
