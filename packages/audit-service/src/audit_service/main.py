"""Audit Service — FastAPI application."""
from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from accounting_shared.database import create_engine, create_session_factory
from accounting_shared.exceptions import register_exception_handlers
from accounting_shared.logging import setup_logging
from accounting_shared.middleware.request_id import RequestIDMiddleware
from accounting_shared.middleware.tenant_context import TenantContextMiddleware

from audit_service.config import AuditSettings
from audit_service.modules.audit.interfaces.api.router import router as audit_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: setup and teardown."""
    settings = AuditSettings()  # type: ignore[call-arg]
    setup_logging(log_level=settings.log_level)

    engine = create_engine(settings)
    session_factory = create_session_factory(engine)

    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory

    yield

    await engine.dispose()


app = FastAPI(
    title="Audit Service",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestIDMiddleware)
app.add_middleware(TenantContextMiddleware)

register_exception_handlers(app)

app.include_router(audit_router, prefix="/audit")


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}
