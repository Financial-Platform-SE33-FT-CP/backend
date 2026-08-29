"""AR/AP Service - FastAPI application."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from accounting_shared.database import create_engine, create_session_factory
from accounting_shared.exceptions import register_exception_handlers
from accounting_shared.logging import setup_logging
from accounting_shared.middleware.audit_context import AuditContextMiddleware
from accounting_shared.middleware.request_id import RequestIDMiddleware
from accounting_shared.middleware.tenant_context import TenantContextMiddleware
from ar_ap_service.config import ArApSettings
from ar_ap_service.infrastructure.orm_registry import register_ar_ap_orm_metadata
from ar_ap_service.modules.ar_ap.interfaces.api.router import router as ar_ap_router

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = ArApSettings()
    setup_logging(settings.log_level)
    register_ar_ap_orm_metadata()
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    app.state.engine = engine
    app.state.session_factory = session_factory
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    settings = ArApSettings()

    app = FastAPI(
        title="AR/AP Service",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Match ledger/coa: explicit origins (required when browser sends Authorization).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(
        AuditContextMiddleware,
        jwt_secret=settings.jwt_secret,
        jwt_algorithm=settings.jwt_algorithm,
    )
    app.add_middleware(TenantContextMiddleware)

    register_exception_handlers(app)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "unhandled_exception",
            path=str(request.url.path),
            exc_type=type(exc).__name__,
        )
        headers: dict[str, str] = {}
        origin = request.headers.get("origin")
        if origin and ("*" in settings.cors_origins or origin in settings.cors_origins):
            headers["Access-Control-Allow-Origin"] = origin
            headers["Access-Control-Allow-Credentials"] = "true"
            headers["Vary"] = "Origin"
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
            headers=headers,
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(ar_ap_router, prefix="/ar-ap")
    return app


app = create_app()
