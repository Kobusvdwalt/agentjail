from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from agentjail.sandbox.filesystem import PathTraversalError
from agentjail.sandbox.manager import SandboxManager, SandboxNotFound

router = APIRouter()


def get_manager(request: Request) -> SandboxManager:
    return request.app.state.manager


def _handle_errors(sandbox_id: str):
    """Return a dict of exception types to HTTPException factories."""
    return {
        SandboxNotFound: lambda: HTTPException(
            status_code=404, detail=f"Sandbox {sandbox_id} not found"
        ),
        PathTraversalError: lambda: HTTPException(
            status_code=400, detail="Path escapes sandbox root"
        ),
        FileNotFoundError: lambda: HTTPException(
            status_code=404, detail="File or directory not found"
        ),
        PermissionError: lambda: HTTPException(
            status_code=403, detail="Permission denied"
        ),
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


@router.post("/sandbox/{sandbox_id}/fs/upload")
async def fs_upload(
    sandbox_id: str,
    file: UploadFile = File(...),
    manager: SandboxManager = Depends(get_manager),
) -> dict:
    content = await file.read()
    path = f"/uploads/{file.filename}"
    await _try(sandbox_id, manager.sandbox_fs_write(sandbox_id, path, content))
    return {"status": "written", "path": path}


@router.get("/sandbox/{sandbox_id}/fs/download")
async def fs_download(
    sandbox_id: str,
    path: str,
    manager: SandboxManager = Depends(get_manager),
) -> FileResponse:
    resolved = await _try(sandbox_id, manager.sandbox_fs_download(sandbox_id, path))
    return FileResponse(resolved, filename=resolved.name)


@router.post("/sandbox/{sandbox_id}/download")
async def sandbox_download(
    sandbox_id: str,
    path: str,
    manager: SandboxManager = Depends(get_manager),
) -> dict:
    return await _try(sandbox_id, manager.sandbox_download(sandbox_id, path))


@router.get("/sandbox/{sandbox_id}/downloads/{filename}")
async def sandbox_download_file(
    sandbox_id: str,
    filename: str,
    manager: SandboxManager = Depends(get_manager),
) -> FileResponse:
    resolved = await _try(
        sandbox_id, manager.sandbox_download_resolve(sandbox_id, filename)
    )
    return FileResponse(resolved, filename=resolved.name)
