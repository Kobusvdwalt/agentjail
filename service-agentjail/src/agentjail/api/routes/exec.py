from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from agentjail.sandbox.manager import SandboxManager, SandboxNotFound, SandboxNotRunning
from agentjail.sandbox.models import ExecResult

router = APIRouter()


def get_manager(request: Request) -> SandboxManager:
    return request.app.state.manager


class ShellRequest(BaseModel):
    command: str
    timeout: int | None = None


@router.post("/sandbox/{sandbox_id}/shell")
async def sandbox_shell(
    sandbox_id: str,
    body: ShellRequest,
    manager: SandboxManager = Depends(get_manager),
) -> ExecResult:
    try:
        return await manager.sandbox_shell(
            sandbox_id, body.command, timeout=body.timeout
        )
    except SandboxNotFound:
        raise HTTPException(status_code=404, detail=f"Sandbox {sandbox_id} not found")
    except SandboxNotRunning:
        raise HTTPException(
            status_code=409, detail=f"Sandbox {sandbox_id} is not running"
        )
