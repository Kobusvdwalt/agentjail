from fastapi import APIRouter, Depends, Request

from agentjail.sandbox.manager import SandboxManager
from agentjail.sandbox.models import StateFile

router = APIRouter()


def get_manager(request: Request) -> SandboxManager:
    return request.app.state.manager


@router.get("/state")
async def get_state(manager: SandboxManager = Depends(get_manager)) -> StateFile:
    """Every sandbox, assembled from the sandbox directory.

    No longer backed by a state file, but the response is unchanged: this is
    the documented health check, and callers key off `version`.
    """
    sandboxes = await manager.sandbox_list()
    return StateFile(sandboxes={sandbox.id: sandbox for sandbox in sandboxes})
