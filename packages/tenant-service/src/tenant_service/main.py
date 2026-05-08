from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from accounting_shared.exceptions import AppException
from accounting_shared.logging import setup_logging
from accounting_shared.middleware.request_id import RequestIDMiddleware
from accounting_shared.middleware.tenant_context import TenantContextMiddleware

from .config import TenantSettings
from .modules.tenants.interfaces.api.router import router as tenants_router

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: startup and shutdown."""
    settings = TenantSettings()
    setup_logging(settings)
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

    # Routers
    app.include_router(tenants_router)

    # Exception handlers
    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
        logger.warning("app_exception", exc=str(exc), path=str(request.url))
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "code": exc.code},
        )

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
