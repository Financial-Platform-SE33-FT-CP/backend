from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from accounting_shared.exceptions import setup_exception_handlers
from accounting_shared.logging import setup_logging
from accounting_shared.middleware.request_id import RequestIdMiddleware
from accounting_shared.middleware.tenant_context import TenantContextMiddleware

from coa_service.config import COASettings
from coa_service.modules.coa.interfaces.api.router import router as coa_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    settings = COASettings()
    app.state.settings = settings
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Chart of Accounts Service",
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
    app.add_middleware(TenantContextMiddleware)
    app.add_middleware(RequestIdMiddleware)

    setup_exception_handlers(app)

    @app.get("/health")
    async def health():
        return {"status": "healthy"}

    app.include_router(coa_router, prefix="/coa")

    return app


app = create_app()
