from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from agentjail.sandbox.manager import (
    SandboxManager,
    SandboxNotFound,
    SandboxStillRunning,
)
from agentjail.sandbox.models import ExecResult, SandboxState

router = APIRouter()


def get_manager(request: Request) -> SandboxManager:
    return request.app.state.manager


class SandboxRunRequest(BaseModel):
    command: str
    time_limit: int | None = None
    memory_limit: int | None = None
    env: dict[str, str] | None = None


class SandboxRunResponse(BaseModel):
    result: ExecResult
    sandbox_id: str


class SandboxCreateRequest(BaseModel):
    name: str | None = None
    time_limit: int | None = None
    memory_limit: int | None = None
    pids_limit: int | None = None
    env: dict[str, str] | None = None
    cwd: str = "/home"
    network: bool = False


@router.post("/sandbox/run")
async def sandbox_run(
    body: SandboxRunRequest, manager: SandboxManager = Depends(get_manager)
) -> SandboxRunResponse:
    result, sandbox_id = await manager.sandbox_run(
        body.command,
        time_limit=body.time_limit,
        memory_limit=body.memory_limit,
        env=body.env,
    )
    return SandboxRunResponse(result=result, sandbox_id=sandbox_id)


@router.post("/sandbox")
async def sandbox_create(
    body: SandboxCreateRequest, manager: SandboxManager = Depends(get_manager)
) -> SandboxState:
    return await manager.sandbox_create(
        name=body.name,
        time_limit=body.time_limit,
        memory_limit=body.memory_limit,
        pids_limit=body.pids_limit,
        env=body.env,
        cwd=body.cwd,
        network=body.network,
    )


@router.get("/sandbox")
async def sandbox_list(
    manager: SandboxManager = Depends(get_manager),
) -> list[SandboxState]:
    return await manager.sandbox_list()


@router.get("/sandbox/{sandbox_id}")
async def sandbox_inspect(
    sandbox_id: str, manager: SandboxManager = Depends(get_manager)
) -> SandboxState:
    try:
        return await manager.sandbox_inspect(sandbox_id)
    except SandboxNotFound:
        raise HTTPException(status_code=404, detail=f"Sandbox {sandbox_id} not found")


@router.post("/sandbox/{sandbox_id}/stop")
async def sandbox_stop(
    sandbox_id: str, manager: SandboxManager = Depends(get_manager)
) -> SandboxState:
    try:
        return await manager.sandbox_stop(sandbox_id)
    except SandboxNotFound:
        raise HTTPException(status_code=404, detail=f"Sandbox {sandbox_id} not found")


@router.delete("/sandbox/{sandbox_id}")
async def sandbox_remove(
    sandbox_id: str,
    force: bool = False,
    manager: SandboxManager = Depends(get_manager),
) -> dict:
    try:
        await manager.sandbox_remove(sandbox_id, force=force)
        return {"status": "removed", "sandbox_id": sandbox_id}
    except SandboxNotFound:
        raise HTTPException(status_code=404, detail=f"Sandbox {sandbox_id} not found")
    except SandboxStillRunning:
        raise HTTPException(
            status_code=409,
            detail=f"Sandbox {sandbox_id} is still running. Use force=true to remove.",
        )
