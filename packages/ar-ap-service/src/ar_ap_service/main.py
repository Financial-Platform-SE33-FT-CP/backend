"""AR/AP Service - FastAPI application."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from accounting_shared.database import create_engine, create_session_factory
from accounting_shared.exceptions import register_exception_handlers
from accounting_shared.logging import setup_logging
from accounting_shared.middleware.request_id import RequestIDMiddleware
from accounting_shared.middleware.tenant_context import TenantContextMiddleware
from ar_ap_service.deps import get_settings
from ar_ap_service.modules.ar_ap.interfaces.api.router import router as ar_ap_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    setup_logging(settings.log_level)
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    app.state.engine = engine
    app.state.session_factory = session_factory
    yield
    await engine.dispose()


app = FastAPI(
    title="AR/AP Service",
    version="0.1.0",
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


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(ar_ap_router, prefix="/ar-ap")
