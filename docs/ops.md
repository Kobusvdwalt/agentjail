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

## Docker setup

### nsjail runner (default)

Requires elevated privileges for nsjail to create Linux namespaces:

```yaml
# docker-compose.yml
cap_add:
  - SYS_ADMIN          # required for nsjail namespaces
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
