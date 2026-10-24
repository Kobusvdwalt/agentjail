import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from agentjail.sandbox.manager import (
    SandboxCapacityExceeded,
    SandboxManager,
    SandboxNotFound,
    SandboxNotRunning,
)
from agentjail.sandbox.models import ExecResult

router = APIRouter()


def get_manager(request: Request) -> SandboxManager:
    return request.app.state.manager


class ShellRequest(BaseModel):
    command: str = Field(min_length=1, max_length=131_072)
    timeout: int | None = Field(default=None, gt=0)
    lease_token: str = Field(min_length=1, max_length=128)


async def _wait_for_disconnect(request: Request) -> None:
    while (await request.receive())["type"] != "http.disconnect":
        pass


@router.post("/sandbox/{sandbox_id}/shell")
async def sandbox_shell(
    sandbox_id: str,
    body: ShellRequest,
    request: Request,
    manager: SandboxManager = Depends(get_manager),
) -> ExecResult:
    execution = asyncio.create_task(
        manager.sandbox_shell(
            sandbox_id,
            body.command,
            timeout=body.timeout,
            lease_token=body.lease_token,
        )
    )
    disconnected = asyncio.create_task(_wait_for_disconnect(request))
    try:
        done, _ = await asyncio.wait(
            [execution, disconnected], return_when=asyncio.FIRST_COMPLETED
        )
        if execution in done:
            return await execution
        raise HTTPException(status_code=499, detail="Client disconnected")
    except SandboxNotFound:
        raise HTTPException(status_code=404, detail=f"Sandbox {sandbox_id} not found")
    except SandboxNotRunning:
        raise HTTPException(
            status_code=409, detail=f"Sandbox {sandbox_id} is not running"
        )
    except SandboxCapacityExceeded:
        raise HTTPException(status_code=429, detail="Execution capacity exhausted")
    finally:
        execution.cancel()
        disconnected.cancel()
        await asyncio.gather(execution, disconnected, return_exceptions=True)
