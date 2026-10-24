from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import AwareDatetime, BaseModel, Field
from uuid import UUID

from agentjail.sandbox.manager import (
    SandboxManager,
    SandboxNotFound,
    SandboxStillRunning,
)
from agentjail.sandbox.models import SandboxState
from agentjail.sandbox.lease import LeaseGrant

router = APIRouter()


def get_manager(request: Request) -> SandboxManager:
    return request.app.state.manager


class SandboxCreateRequest(BaseModel):
    name: str | None = None
    time_limit: int | None = Field(default=None, gt=0)
    memory_limit: int | None = Field(default=None, gt=0)
    pids_limit: int | None = Field(default=None, gt=0)
    env: dict[str, str] | None = None
    cwd: str = "/home"
    network: bool = False
    resources: list[str] | None = None
    """Glob patterns for the shared resources this sandbox may see.

    Relative to the resources directory: `["vigil-api/**", "shared/**"]`. Omit
    it — or pass `["*"]` — for everything. `[]` gives the sandbox none.
    """


class LeaseRequest(BaseModel):
    lease_seconds: int = Field(default=120, ge=1, le=300)
    not_after: AwareDatetime | None = None


class ReleaseLeaseRequest(BaseModel):
    lease_token: str = Field(min_length=1, max_length=128)


class RenewLeaseRequest(LeaseRequest, ReleaseLeaseRequest):
    pass


@router.post("/sandbox/{sandbox_id}/lease")
async def acquire_lease(
    sandbox_id: str,
    body: LeaseRequest,
    manager: SandboxManager = Depends(get_manager),
) -> LeaseGrant:
    return await manager.acquire_lease(sandbox_id, body.lease_seconds, body.not_after)


@router.post("/sandbox/{sandbox_id}/lease/renew")
async def renew_lease(
    sandbox_id: str,
    body: RenewLeaseRequest,
    manager: SandboxManager = Depends(get_manager),
) -> LeaseGrant:
    return await manager.renew_lease(
        sandbox_id, body.lease_token, body.lease_seconds, body.not_after
    )


@router.post("/sandbox/{sandbox_id}/lease/release")
async def release_lease(
    sandbox_id: str,
    body: ReleaseLeaseRequest,
    manager: SandboxManager = Depends(get_manager),
) -> SandboxState:
    return await manager.release_lease(sandbox_id, body.lease_token)


@router.put("/sandbox/{workspace_id}")
async def ensure_workspace(
    workspace_id: UUID,
    body: SandboxCreateRequest,
    manager: SandboxManager = Depends(get_manager),
) -> SandboxState:
    return await manager.sandbox_create(workspace_id=workspace_id, **body.model_dump())


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
        resources=body.resources,
    )


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
