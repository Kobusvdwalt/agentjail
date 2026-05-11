# Architecture

## Overview

Sandboxed command execution service for AI agents. Provides isolated environments via MCP (for Claude/Cursor) and a REST API. Supports pluggable sandbox runners — currently **nsjail** (full isolation, requires `CAP_SYS_ADMIN`) and **chroot** (user-namespace isolation, works on restrictive Kubernetes clusters).

## Single process, single port

FastMCP is mounted as an ASGI sub-app inside FastAPI. One uvicorn process serves both MCP (`/mcp`) and REST API (`/api/v1/...`) on port 8000.

## Two sandbox modes

1. **Ephemeral** (`POST /api/v1/sandbox/run`) — creates a temp directory, runs a single command, deletes the directory. No state persisted.
2. **Persistent** (`POST /api/v1/sandbox` → exec/shell) — creates a sandbox with a UUID, stores state in a JSON file. The sandbox's writable directory persists across exec calls until explicitly removed.

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

## JSON state file

Configurable path via `AGENTJAIL_STATE_FILE`. Thread-safe via `filelock`, atomic writes via temp file + `os.replace()`.
