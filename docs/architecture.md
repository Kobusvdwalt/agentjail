# Architecture

## Overview

Sandboxed command execution service for AI agents. Provides isolated environments via MCP (for Claude/Cursor) and a REST API. Supports pluggable sandbox runners — currently **nsjail** (full isolation, requires `CAP_SYS_ADMIN`) and **chroot** (user-namespace isolation, works on restrictive Kubernetes clusters).

## Single process, single port

FastMCP is mounted as an ASGI sub-app inside FastAPI. One uvicorn process serves both MCP (`/mcp`) and REST API (`/api/v1/...`) on port 8000.

## Sandbox modes

1. **Persistent API mode** (`POST /api/v1/sandbox` → shell/filesystem routes) — creates a sandbox with a UUID, stores state in a JSON file. The sandbox's writable directory persists across calls until explicitly removed.
2. **Ephemeral manager mode** (`SandboxManager.sandbox_run()`) — creates a temp directory, runs a single command, and deletes the directory. This mode exists in the manager layer but is not exposed as a REST endpoint in the current API surface.

## No long-running daemon

Each command spawns a fresh isolation process (nsjail or chroot helper). "Running" means "can accept commands", not "has a live process". State is tracked in a JSON file, not by process liveness.

## Pluggable runner architecture

The `AGENTJAIL_RUNNER` environment variable selects the isolation backend. The `SandboxManager` delegates to whichever runner is configured — the rest of the system (API, MCP, state management, filesystem operations) is runner-agnostic.

Currently supported runners:

| Runner | Env value | Requires | Best for |
|---|---|---|---|
| **nsjail** | `nsjail` (default) | `CAP_SYS_ADMIN`, `apparmor=unconfined`, `seccomp=unconfined` | Docker Compose, unrestricted environments |
| **chroot** | `chroot` | No special capabilities | Kubernetes (baseline PodSecurity), restricted environments |

Adding a new runner requires implementing `setup_sandbox(root_dir)` and `run_command(sandbox, command, timeout, env, cwd) -> ExecResult`, then registering it in `manager.py`.

## Filesystem layout (both runners)

Each sandbox root directory (`<sandbox_base_dir>/<uuid>/`) has:
- `home/` — the user-writable workspace, mounted/chrooted as `/home` inside the sandbox
- `tmp/` — (chroot only) cleaned between commands

System binaries (`/usr`, `/lib`, `/bin`, etc.) are provided via bind mounts (nsjail) or copies/symlinks (chroot).

## Shared resources

An optional host directory (`AGENTJAIL_RESOURCES_DIR`, default `/var/lib/agentjail/resources`) is bind-mounted read-only at `/resources` inside every sandbox. All sandboxes share the same files — no copies are made. Host changes are visible immediately. If the directory doesn't exist, the mount is skipped.

## Base image pattern

The production Dockerfile builds a **self-contained agentjail tree** under `/opt/agentjail` containing the nsjail binary, a uv-managed Python interpreter, and the agentjail venv. This entire tree can be copied into any Docker image with a single `COPY --from`:

```dockerfile
FROM python:3.12-slim
COPY --from=agentjail:latest /opt/agentjail /opt/agentjail
```

The `/opt/agentjail` tree contains:
- `.venv/` — Python venv with agentjail installed (entry point: `agentjail`)
- `python/` — uv-managed Python interpreter (the venv links to this)
- `bin/nsjail` — nsjail binary
- `lib/` — nsjail's runtime shared libraries (libprotobuf, libnl), found via RPATH baked into the binary
- `config/` — reference nsjail config

The target image needs no extra dependencies or env vars — everything is bundled. Just `COPY --from` and go.

See `docs/examples/` for sample Dockerfiles adding Python, Go, and Bun.

## JSON state file

Configurable path via `AGENTJAIL_STATE_FILE`. Thread-safe via `filelock`, atomic writes via temp file + `os.replace()`.
