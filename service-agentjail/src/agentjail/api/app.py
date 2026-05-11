from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from agentjail.api.routes import exec, filesystem, sandbox, state
from agentjail.sandbox.manager import SandboxManager


def create_api(manager: SandboxManager, lifespan=None) -> FastAPI:
    @asynccontextmanager
    async def wrapped_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        if lifespan is not None:
            async with lifespan(app):
                yield
        else:
            yield

    app = FastAPI(title="agentjail", version="0.1.0", lifespan=wrapped_lifespan)
    app.state.manager = manager
    app.include_router(sandbox.router, prefix="/api/v1", tags=["sandbox"])
    app.include_router(exec.router, prefix="/api/v1", tags=["exec"])
    app.include_router(filesystem.router, prefix="/api/v1", tags=["filesystem"])
    app.include_router(state.router, prefix="/api/v1", tags=["state"])
    return app
