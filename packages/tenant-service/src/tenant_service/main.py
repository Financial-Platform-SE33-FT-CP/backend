from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from accounting_shared.exceptions import register_exception_handlers
from accounting_shared.logging import setup_logging
from accounting_shared.middleware.request_id import RequestIDMiddleware
from accounting_shared.middleware.tenant_context import TenantContextMiddleware
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import TenantSettings
from .modules.tenants.interfaces.api.internal_router import router as internal_router
from .modules.tenants.interfaces.api.router import router as tenants_router

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: startup and shutdown."""
    settings = TenantSettings()
    setup_logging(settings.log_level)
    logger.info("tenant_service_starting", service=settings.service_name)
    yield
    logger.info("tenant_service_shutdown")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = TenantSettings()

    app = FastAPI(
        title="Tenant Service",
        description="Tenant management service for Accounting Platform",
        version="0.1.0",
        lifespan=lifespan,
    )

    register_exception_handlers(app)

    # Middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(TenantContextMiddleware)

    app.include_router(tenants_router)
    app.include_router(internal_router)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        logger.error("unhandled_exception", exc=str(exc), path=str(request.url))
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    # Health check
    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "healthy", "service": settings.service_name}

    return app


app = create_app()
