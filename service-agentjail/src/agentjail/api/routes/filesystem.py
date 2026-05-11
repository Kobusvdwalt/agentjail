from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from agentjail.sandbox.filesystem import PathTraversalError
from agentjail.sandbox.manager import SandboxManager, SandboxNotFound
from agentjail.sandbox.models import FileInfo

router = APIRouter()


def get_manager(request: Request) -> SandboxManager:
    return request.app.state.manager


class WriteRequest(BaseModel):
    path: str
    content: str


class MkdirRequest(BaseModel):
    path: str


def _handle_errors(sandbox_id: str):
    """Return a dict of exception types to HTTPException factories."""
    return {
        SandboxNotFound: lambda: HTTPException(status_code=404, detail=f"Sandbox {sandbox_id} not found"),
        PathTraversalError: lambda: HTTPException(status_code=400, detail="Path escapes sandbox root"),
        FileNotFoundError: lambda: HTTPException(status_code=404, detail="File or directory not found"),
        PermissionError: lambda: HTTPException(status_code=403, detail="Permission denied"),
    }


async def _try(sandbox_id: str, coro):
    handlers = _handle_errors(sandbox_id)
    try:
        return await coro
    except tuple(handlers.keys()) as e:
        for exc_type, factory in handlers.items():
            if isinstance(e, exc_type):
                raise factory()
        raise


@router.get("/sandbox/{sandbox_id}/fs/read")
async def fs_read(
    sandbox_id: str,
    path: str,
    manager: SandboxManager = Depends(get_manager),
) -> dict:
    content = await _try(sandbox_id, manager.sandbox_fs_read(sandbox_id, path))
    return {"path": path, "content": content}


@router.post("/sandbox/{sandbox_id}/fs/write")
async def fs_write(
    sandbox_id: str,
    body: WriteRequest,
    manager: SandboxManager = Depends(get_manager),
) -> dict:
    await _try(sandbox_id, manager.sandbox_fs_write(sandbox_id, body.path, body.content))
    return {"status": "written", "path": body.path}


@router.get("/sandbox/{sandbox_id}/fs/list")
async def fs_list(
    sandbox_id: str,
    path: str = "/",
    manager: SandboxManager = Depends(get_manager),
) -> list[FileInfo]:
    return await _try(sandbox_id, manager.sandbox_fs_list(sandbox_id, path))


@router.post("/sandbox/{sandbox_id}/fs/mkdir")
async def fs_mkdir(
    sandbox_id: str,
    body: MkdirRequest,
    manager: SandboxManager = Depends(get_manager),
) -> dict:
    await _try(sandbox_id, manager.sandbox_fs_mkdir(sandbox_id, body.path))
    return {"status": "created", "path": body.path}


@router.delete("/sandbox/{sandbox_id}/fs")
async def fs_remove(
    sandbox_id: str,
    path: str,
    manager: SandboxManager = Depends(get_manager),
) -> dict:
    await _try(sandbox_id, manager.sandbox_fs_remove(sandbox_id, path))
    return {"status": "removed", "path": path}


@router.get("/sandbox/{sandbox_id}/fs/stat")
async def fs_stat(
    sandbox_id: str,
    path: str,
    manager: SandboxManager = Depends(get_manager),
) -> FileInfo:
    return await _try(sandbox_id, manager.sandbox_fs_stat(sandbox_id, path))
