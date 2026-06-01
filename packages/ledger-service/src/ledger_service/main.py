from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import structlog

from accounting_shared.database import create_engine, create_session_factory
from accounting_shared.exceptions import register_exception_handlers
from accounting_shared.logging import setup_logging
from accounting_shared.middleware.request_id import RequestIDMiddleware
from accounting_shared.middleware.tenant_context import TenantContextMiddleware

from ledger_service.deps import get_settings
from ledger_service.modules.ledger.interfaces.api.router import router as ledger_router
from ledger_service.modules.opening_balance.interfaces.api.router import (
    router as opening_balance_router,
)
from ledger_service.modules.opening_balance.infrastructure.orm_registry import (
    register_opening_balance_orm_metadata,
)

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings.log_level)
    register_opening_balance_orm_metadata()
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    app.state.engine = engine
    app.state.session_factory = session_factory
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="Ledger Service", lifespan=lifespan)

    settings = get_settings()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(TenantContextMiddleware)

    register_exception_handlers(app)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        logger.error("unhandled_exception", exc=str(exc), path=str(request.url.path))
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    app.include_router(ledger_router, prefix="/ledger")
    app.include_router(opening_balance_router, prefix="/ledger")

    return app


app = create_app()
