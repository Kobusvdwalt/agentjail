# Source File Map

Quick reference for agents modifying this codebase.

## Core

| File | Purpose |
|---|---|
| `src/agentjail/config.py` | `AgentjailSettings` (pydantic-settings). All tunable values, env prefix `AGENTJAIL_`. Includes `runner` field and `bind_mount_ro` list. |
| `src/agentjail/server.py` | `create_app()` — instantiates settings, manager, MCP, and FastAPI. Mounts MCP at `/mcp`. |
| `src/agentjail/cli.py` | Typer CLI entry point. Calls `run_server()`. |
| `src/agentjail/state.py` | `StateManager` — JSON state file with `filelock` + atomic writes via `os.replace()`. |

## Sandbox

| File | Purpose |
|---|---|
| `src/agentjail/sandbox/models.py` | Pydantic models: `SandboxConfig`, `SandboxState`, `ExecResult`, `FileInfo`, `StateFile`. |
| `src/agentjail/sandbox/manager.py` | `SandboxManager` — all sandbox lifecycle + filesystem operations. Selects runner based on `settings.runner`. |
| `src/agentjail/sandbox/nsjail.py` | `NsjailRunner` — builds nsjail CLI args and runs subprocess. `_build_args()` is where all nsjail flags are assembled. |
| `src/agentjail/sandbox/chroot.py` | `ChrootRunner` — chroot + user-namespace sandbox. `setup_sandbox()` copies system dirs, `run_command()` invokes the helper. |
| `src/agentjail/sandbox/_chroot_exec.py` | Helper script invoked as subprocess by `ChrootRunner`. Performs unshare → uid map → chroot → rlimits → fork → execve. |
| `src/agentjail/sandbox/filesystem.py` | Host-side filesystem operations (`fs_read`, `fs_write`, etc.) with `_resolve_safe()` path traversal protection. |

## API

| File | Purpose |
|---|---|
| `src/agentjail/api/app.py` | FastAPI app factory. Registers route modules. |
| `src/agentjail/api/routes/sandbox.py` | REST routes: create, list, inspect, stop, remove, ephemeral run. |
| `src/agentjail/api/routes/exec.py` | REST routes: shell (via /bin/sh -c). |
| `src/agentjail/api/routes/filesystem.py` | REST routes: fs read/write/list/mkdir/remove/stat. |
| `src/agentjail/api/routes/state.py` | REST route: raw state file dump (to be removed). |
| `src/agentjail/mcp/server.py` | FastMCP tool definitions (13 tools). Uses global `_manager`. |

## Infrastructure

| File | Purpose |
|---|---|
| `config/nsjail_default.cfg` | Reference/documentation nsjail config (NOT used at runtime — args built in Python). |
| `Dockerfile` | Production image — multi-stage (nsjail build + runtime). Currently runs as root (to be fixed). |
| `dev.dockerfile` | Dev image — uses `python:3.14-slim`, runs as `service` user, has `--reload`. |
| `default.env` | Default environment variables for docker-compose. |
