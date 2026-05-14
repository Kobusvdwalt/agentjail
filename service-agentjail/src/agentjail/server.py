import uvicorn
from fastapi import FastAPI

from agentjail.api.app import create_api
from agentjail.config import AgentjailSettings
from agentjail.mcp.server import init_mcp
from agentjail.sandbox.manager import SandboxManager


def create_app() -> FastAPI:
    settings = AgentjailSettings()
    manager = SandboxManager(settings)

    mcp_server = init_mcp(manager, settings)
    mcp_app = mcp_server.http_app(path="/")

    api_app = create_api(manager, lifespan=mcp_app.lifespan)
    api_app.mount("/mcp", mcp_app)

    return api_app


def run_server(host: str = "0.0.0.0", port: int = 8000) -> None:
    app = create_app()
    uvicorn.run(app, host=host, port=port)
