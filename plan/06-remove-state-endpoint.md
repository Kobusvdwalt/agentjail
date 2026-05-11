# Plan 06: Remove the /api/v1/state Endpoint

## Goal

Remove the `GET /api/v1/state` endpoint that exposes the raw state file.

## Why

This endpoint returns the full internal state including `root_dir` absolute paths for every sandbox, which leaks host filesystem structure. The `sandbox_list` and `sandbox_inspect` endpoints already provide all the information a client needs.

## Files to Change

### 1. Delete `service-agentjail/src/agentjail/api/routes/state.py`

Delete the entire file. Current contents:
```python
from fastapi import APIRouter, Depends, Request
from agentjail.sandbox.manager import SandboxManager
from agentjail.sandbox.models import StateFile

router = APIRouter()

def get_manager(request: Request) -> SandboxManager:
    return request.app.state.manager

@router.get("/state")
async def get_state(manager: SandboxManager = Depends(get_manager)) -> StateFile:
    return manager.state.read()
```

### 2. Update `service-agentjail/src/agentjail/api/app.py`

Remove the import and router registration:

```python
# Remove this import:
from agentjail.api.routes import exec, filesystem, sandbox, state

# Change to:
from agentjail.api.routes import exec, filesystem, sandbox

# Remove this line:
app.include_router(state.router, prefix="/api/v1", tags=["state"])
```

### 3. Update `service-agentjail/src/agentjail/api/routes/__init__.py`

If it imports `state`, remove that import. (Currently the file is likely empty or just has route imports.)

### 4. Also consider: strip `root_dir` from API responses

The `SandboxState` model includes `root_dir` (an internal host path like `/var/lib/agentjail/sandboxes/<id>`). This is returned by `sandbox_create`, `sandbox_inspect`, `sandbox_list`, `sandbox_stop`, and the MCP equivalents.

**Optional but recommended:** Create a `SandboxResponse` model that excludes `root_dir`:

```python
class SandboxResponse(BaseModel):
    id: str
    name: str | None
    status: Literal["created", "running", "stopped"]
    config: SandboxConfig
    created_at: datetime
    updated_at: datetime
    # root_dir intentionally excluded
```

Use `SandboxResponse` as the return type in route handlers instead of `SandboxState`. The internal `SandboxState` (with `root_dir`) remains for the manager/state layer.

This is a separate but related hardening step — decide if you want it in scope.

### 5. Update `docs/DESIGN.md`

Remove from the API Surface section:
```
GET    /api/v1/state                — raw state file
```

## Verification

```bash
docker compose up --build

# Confirm endpoint is gone:
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/v1/state
# Expected: 404 (or 405)

# Confirm other endpoints still work:
curl -s http://localhost:8000/api/v1/sandbox | jq .
# Expected: [] (empty list or list of sandboxes)
```

## Reference

- `service-agentjail/src/agentjail/api/routes/state.py` — file to delete
- `service-agentjail/src/agentjail/api/app.py` — router registration to remove
- `docs/DESIGN.md` — API Surface section to update
- `service-agentjail/src/agentjail/sandbox/models.py` — `SandboxState` model with `root_dir` field
