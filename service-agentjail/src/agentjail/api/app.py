from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Security
from fastapi.security import HTTPBearer
from starlette.responses import JSONResponse

from agentjail.api.auth import BearerAuthMiddleware
from agentjail.api.routes import exec, filesystem, sandbox, state
from agentjail.sandbox.manager import SandboxManager
from agentjail.sandbox.manager import SandboxNotFound, SandboxNotRunning
from agentjail.sandbox.lease import LeaseConflict


def create_api(manager: SandboxManager, lifespan=None) -> FastAPI:
    if manager.settings.api_token is None:
        raise ValueError("AGENTJAIL_API_TOKEN must contain at least 32 characters")

    @asynccontextmanager
    async def wrapped_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        try:
            if lifespan is not None:
                async with lifespan(app):
                    yield
            else:
                yield
        finally:
            await manager.shutdown()

    app = FastAPI(
        title="agentjail",
        version="0.1.0",
        lifespan=wrapped_lifespan,
        dependencies=[Security(HTTPBearer(auto_error=False))],
    )
    app.add_middleware(
        BearerAuthMiddleware, token=manager.settings.api_token.get_secret_value()
    )
    app.state.manager = manager

    @app.exception_handler(LeaseConflict)
    async def lease_conflict(request, error):
        return JSONResponse({"detail": str(error)}, status_code=409)

    @app.exception_handler(SandboxNotFound)
    async def sandbox_not_found(request, error):
        return JSONResponse({"detail": "Sandbox not found"}, status_code=404)

    @app.exception_handler(SandboxNotRunning)
    async def sandbox_not_running(request, error):
        return JSONResponse({"detail": "Sandbox is not running"}, status_code=409)

    app.include_router(sandbox.router, prefix="/api/v1", tags=["sandbox"])
    app.include_router(exec.router, prefix="/api/v1", tags=["exec"])
    app.include_router(filesystem.router, prefix="/api/v1", tags=["filesystem"])
    app.include_router(state.router, prefix="/api/v1", tags=["state"])

    @app.get("/health", include_in_schema=False)
    async def health():
        return {"status": "ok"}

    return app
