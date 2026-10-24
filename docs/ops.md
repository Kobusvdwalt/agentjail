# Operations

## Tech Stack

- Python 3.14 with uv
- FastMCP v3.2.4 — MCP server (streamable-http transport)
- FastAPI + uvicorn — REST API
- Typer — CLI
- nsjail — sandbox isolation (subprocess, no daemon)
- Pydantic / pydantic-settings — config and models
- filelock — thread/process-safe state file
- Docker Compose — local dev with `docker compose watch`

## Configuration

Settings via environment variables (prefix `AGENTJAIL_`):

| Variable | Default | Description |
|---|---|---|
| `AGENTJAIL_API_TOKEN` | required | Random service bearer credential, at least 32 characters; HTTP startup fails without it. |
| `AGENTJAIL_MAX_OUTPUT_BYTES` | `65536` | Retained raw bytes per stdout/stderr stream, range 1–1048576. |
| `AGENTJAIL_MAX_ACTIVE_COMMANDS` | `8` | Active command limit per service, range 1–128; excess returns 429. |
| `AGENTJAIL_HOST` | `0.0.0.0` | Listen address |
| `AGENTJAIL_PORT` | `8000` | Listen port |
| `AGENTJAIL_SANDBOX_BASE_DIR` | `/var/lib/agentjail/sandboxes` | Where sandbox directories are stored |
| `AGENTJAIL_STATE_FILE` | `/var/lib/agentjail/state.json` | Path to the JSON state file |
| `AGENTJAIL_RUNNER` | `nsjail` | Sandbox runner: `nsjail` or `chroot` |
| `AGENTJAIL_NSJAIL_BIN` | `nsjail` | Path to the nsjail binary |
| `AGENTJAIL_RESOURCES_DIR` | `/var/lib/agentjail/resources` | Directory of read-only files injected into every sandbox at `/resources`. Set to empty or remove to disable. |
| `AGENTJAIL_DEFAULT_TIME_LIMIT` | `30` | Default time limit (seconds) |
| `AGENTJAIL_DEFAULT_MEMORY_LIMIT` | `256` | Default memory limit (MB) |
| `AGENTJAIL_DEFAULT_PIDS_LIMIT` | `64` | Default PID limit |
| `AGENTJAIL_MCP_TOOLS` | *(all)* | JSON list of MCP tool names to expose (e.g. `'["sandbox_shell","sandbox_host_file"]'`). When unset, all tools are enabled. |

## Docker setup

### nsjail runner (default)

The example development profile grants broad permissions for namespace creation;
the minimum required profile depends on the target runtime:

```yaml
# docker-compose.yml
cap_add:
  - SYS_ADMIN          # broad development profile; verify whether needed
security_opt:
  - apparmor=unconfined # nsjail needs unrestricted apparmor
  - seccomp=unconfined  # nsjail needs unrestricted seccomp
volumes:
  - ./_volumes/agentjail:/var/lib/agentjail
  - ./_volumes/resources:/var/lib/agentjail/resources:ro  # shared read-only resources
```

These privileges are for the **container** — nsjail creates unprivileged sandboxes inside it.

### chroot runner

No special privileges required. Works with default Docker security policies and Kubernetes baseline PodSecurity:

```yaml
# docker-compose.yml
environment:
  - AGENTJAIL_RUNNER=chroot
volumes:
  - ./_volumes/agentjail:/var/lib/agentjail
```

## Base Image

The production `Dockerfile` builds a self-contained `/opt/agentjail` tree (Python + venv + nsjail) that can be used two ways:

### 1. Use the image directly
```bash
docker run -p 127.0.0.1:8000:8000 --env AGENTJAIL_API_TOKEN --cap-add SYS_ADMIN agentjail:latest
```

### 2. COPY --from into your own image
```dockerfile
FROM python:3.12-slim
COPY --from=agentjail:latest /opt/agentjail /opt/agentjail
```

The tree is fully self-contained — no system Python, uv, pip, or extra apt packages needed. nsjail's runtime libraries are bundled with RPATH baked in, so no env vars are required.

See `docs/examples/` for complete Dockerfiles (Python, Go, Bun).

## Development

```bash
# Start with hot-reload
docker compose up --build --watch

# Source files sync into the container automatically
# pyproject.toml changes trigger a rebuild
```

## What's been tested and works

- Shell scripts, loops, pipes, multi-command chains
- Environment variable passthrough (sandbox config + per-call)
- File I/O inside sandboxes (write via shell, read back)
- Python 3.14 execution inside sandboxes
- Subprocess spawning inside sandboxes (Python subprocess module works)
- Sandbox lifecycle: create → inspect → list → stop → remove
- curl and HTTPS (with `network: true`) — `ca-certificates` and `curl` are installed in the container image
- DNS resolution works when sandbox is created with `network: true`
- exec with args (direct binary execution)
- shell (via /bin/sh -c)
- Filesystem API: mkdir, write, read, list, stat, remove
- Filesystem API ↔ shell interop (write via API, read from shell and vice versa)
- Path traversal protection (returns 400)
- Filesystem isolation (can't read host paths like state file)
- Error handling: 404 for missing sandbox, 409 for removing running sandbox
- Non-zero exit codes preserved
- pip install works (with network enabled, nsjail only)
- Files persist across exec/shell calls on the same sandbox
- Host volume visibility (_volumes/agentjail/sandboxes/)
- Both nsjail and chroot runners verified working

## Authenticated rollout and recovery

Supply `AGENTJAIL_API_TOKEN` through a secret manager/environment injection, never
a committed value or an image layer. Compose requires it from the host environment.
Use TLS on production control-plane connections and restrict access to supervisors.
Do not mount service tokens, workload identity tokens or Kubernetes credentials
inside accessible sandbox paths. Hosted downloads require the same authentication.

Update every REST/MCP client to authenticate and acquire/renew execution leases
before deploying this breaking contract. Rotate the service token by restarting
the service and clients together. Restart invalidates in-memory execution leases;
persistent files/configuration remain when the state file and sandbox directories
are on retained storage. The supervisor must reacquire ownership before executing.

Use one service process/replica per state/storage root. Lease authority and task
registries are local to that process; multiple managers over the same JSON file
are unsupported. The CLI allows five seconds for graceful request shutdown before
cancellation; manager shutdown then cancels and drains its registered commands.
An external uvicorn invocation must configure its own graceful shutdown timeout.

Local regression checks: `uv run pytest tests/unit -q` and `uv run ruff check src/ tests/`.
The Vigil worker's opt-in sandbox proof additionally checks real nsjail and Mastra
execution. Container profile and persistent-volume recovery still need a separate
AKS verification. Do not deploy a seccomp-unconfined profile on that evidence alone.

To reproduce the local nsjail proof without changing the underlying nsjail/runtime
build, run `docker build -f Dockerfile.verify -t vigil-agentjail:379-hardening .`
from `service-agentjail/`. This verification Dockerfile overlays current Python
source on the digest-pinned baseline image. It is a regression fixture; it does
not replace production image pinning or AKS validation.
