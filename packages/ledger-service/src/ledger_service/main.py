from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from accounting_shared.database import create_engine, create_session_factory
from accounting_shared.exception_handlers import register_exception_handlers
from accounting_shared.logging import setup_logging
from accounting_shared.middleware import RequestIDMiddleware, TenantContextMiddleware

from ledger_service.config import LedgerSettings
from ledger_service.deps import get_settings
from ledger_service.modules.ledger.interfaces.api.router import router as ledger_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    settings = get_settings()
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    app.state.engine = engine
    app.state.session_factory = session_factory
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="Ledger Service", lifespan=lifespan)

    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(TenantContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    app.include_router(ledger_router, prefix="/ledger")

    return app


app = create_app()
