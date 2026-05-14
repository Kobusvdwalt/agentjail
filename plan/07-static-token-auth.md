# Plan 07: Static Token Authentication

## Goal

Require a shared secret (Bearer token) on every HTTP request to both the REST API (`/api/v1`) and the MCP transport (`/mcp`). Auth is **on by default** — local development opts out explicitly.

## Why

The API is currently wide open. Anyone who can reach the port can create sandboxes, execute arbitrary commands, and read/write files. A static token is a low-cost defense-in-depth layer that prevents accidental exposure and casual abuse.

## Design Decisions

### Token delivery
- Standard `Authorization: Bearer <token>` header.
- Checked via Starlette middleware on the outer FastAPI app so it covers both `/api/v1` routes and the mounted `/mcp` ASGI sub-app in a single place.

### Config
Two new fields in `AgentjailSettings`:

| Field | Env var | Default | Purpose |
|---|---|---|---|
| `auth_token` | `AGENTJAIL_AUTH_TOKEN` | `None` | The shared secret. When set, every request must present it. |
| `auth_disabled` | `AGENTJAIL_AUTH_DISABLED` | `False` | Explicit opt-out. When `True`, skip token validation even if `auth_token` is unset. |

**Startup behaviour:**
- `auth_token` is set → enforce it on every request.
- `auth_token` is unset and `auth_disabled` is `False` → **refuse to start** with a clear error message ("Set AGENTJAIL_AUTH_TOKEN or explicitly set AGENTJAIL_AUTH_DISABLED=true for local development").
- `auth_token` is unset and `auth_disabled` is `True` → run without auth (local dev / tests).

This makes the secure path the default: you can't accidentally deploy without a token unless you deliberately disable auth.

### What's exempt
- Nothing. Every request is checked when auth is enabled. There's no health-check endpoint that needs to be public.

## Changes

### 1. `config.py` — add settings fields

```python
auth_token: str | None = None
auth_disabled: bool = False
```

### 2. New file `src/agentjail/api/auth.py` — middleware

Create a Starlette `BaseHTTPMiddleware` subclass:

```
class TokenAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, token):
        ...
    async def dispatch(self, request, call_next):
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer ") or header[7:] != self.token:
            return JSONResponse(status_code=401, content={"detail": "Invalid or missing token"})
        return await call_next(request)
```

Uses constant-time comparison (`hmac.compare_digest`) to prevent timing attacks.

### 3. `server.py` — wire up middleware + startup guard

In `create_app()`:

```python
settings = AgentjailSettings()

if not settings.auth_disabled and not settings.auth_token:
    sys.exit("FATAL: Set AGENTJAIL_AUTH_TOKEN or AGENTJAIL_AUTH_DISABLED=true")

...
api_app = create_api(manager, lifespan=mcp_app.lifespan)
api_app.mount("/mcp", mcp_app)

if settings.auth_token:
    api_app.add_middleware(TokenAuthMiddleware, token=settings.auth_token)
```

Middleware is added **after** mounting so it wraps both the API routes and the MCP sub-app.

### 4. `default.env` — document new vars

```
# Auth — set a token for production; disable explicitly for local dev
# AGENTJAIL_AUTH_TOKEN=
AGENTJAIL_AUTH_DISABLED=true
```

`default.env` is the local-dev config, so `AUTH_DISABLED=true` here means `docker compose up` keeps working without changes.

### 5. Unit tests — `tests/unit/conftest.py`

Update the `settings` fixture to disable auth:

```python
return AgentjailSettings(
    ...,
    auth_disabled=True,
)
```

No token needed for unit tests since they test business logic, not auth.

### 6. Integration tests — `tests/integration/conftest.py`

Set a known token in the container env and pass it in the httpx client:

```python
TEST_TOKEN = "test-integration-token"

# In container fixture:
.with_env("AGENTJAIL_AUTH_TOKEN", TEST_TOKEN)

# In client fixture:
httpx.AsyncClient(..., headers={"Authorization": f"Bearer {TEST_TOKEN}"})
```

### 7. New test file — `tests/unit/test_auth.py`

Test cases:
- Request with valid token → 200
- Request with wrong token → 401
- Request with no Authorization header → 401
- Request with malformed header (e.g. `Basic ...`) → 401
- Auth disabled (`auth_disabled=True`, no token) → all requests pass through

### 8. Docs updates

| File | Update |
|---|---|
| `docs/api.md` | Add authentication section: header format, 401 response |
| `docs/ops.md` | Add `AGENTJAIL_AUTH_TOKEN` and `AGENTJAIL_AUTH_DISABLED` to env var table |
| `docs/security.md` | Note the static token layer and its limitations |
| `docs/source-map.md` | Add `api/auth.py` entry |
| `README.md` | Add auth setup to quickstart / configuration section |

## File Summary

| File | Action |
|---|---|
| `src/agentjail/config.py` | Add `auth_token`, `auth_disabled` fields |
| `src/agentjail/api/auth.py` | **New** — `TokenAuthMiddleware` |
| `src/agentjail/server.py` | Startup guard + add middleware |
| `default.env` | Add `AGENTJAIL_AUTH_DISABLED=true` |
| `tests/unit/conftest.py` | Set `auth_disabled=True` in settings fixture |
| `tests/integration/conftest.py` | Set token env var + client header |
| `tests/unit/test_auth.py` | **New** — auth middleware tests |
| `docs/api.md` | Auth section |
| `docs/ops.md` | Env var table |
| `docs/security.md` | Token auth note |
| `docs/source-map.md` | New file entry |
| `README.md` | Auth config |
