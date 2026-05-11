from fastapi import APIRouter, Depends, Request

from agentjail.sandbox.manager import SandboxManager
from agentjail.sandbox.models import StateFile

router = APIRouter()


def get_manager(request: Request) -> SandboxManager:
    return request.app.state.manager


@router.get("/state")
async def get_state(manager: SandboxManager = Depends(get_manager)) -> StateFile:
    return manager.state.read()
