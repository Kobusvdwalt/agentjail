# Architecture

## Overview

Sandboxed command execution service for AI agents. Provides isolated environments via MCP (for Claude/Cursor) and a REST API. Supports pluggable sandbox runners — currently **nsjail** (namespace isolation; container profile must be verified) and **chroot** (user namespaces plus chroot; runtime support must also be verified).

## Single process, single port

FastMCP is mounted as an ASGI sub-app inside FastAPI. One uvicorn process serves both MCP (`/mcp`) and REST API (`/api/v1/...`) on port 8000.

## Sandbox modes

1. **Persistent API mode** (`POST /api/v1/sandbox` → shell/filesystem routes) — creates a sandbox with an opaque random ID, stores state in a JSON file. The sandbox's writable directory persists across calls until explicitly removed.
2. **Ephemeral manager mode** (`SandboxManager.sandbox_run()`) — creates a temp directory, runs a single command, and deletes the directory. This mode exists in the manager layer but is not exposed as a REST endpoint in the current API surface.

## No long-running daemon

Each command spawns a fresh isolation process (nsjail or chroot helper). "Running" means "can accept commands", not "has a live process". Workspace configuration is tracked in a JSON file. Live lease authority,
expiry tasks and registered command tasks belong to one manager process. An
execution lease is mandatory even when a workspace's persisted status is running.
A service restart loses lease authority and requires reacquisition, preserving
workspace files. Run exactly one service process per state/storage root; state
file locks do not fence executions in other service processes.

## Pluggable runner architecture

The `AGENTJAIL_RUNNER` environment variable selects the isolation backend. The `SandboxManager` delegates to whichever runner is configured — the rest of the system (API, MCP, state management, filesystem operations) is runner-agnostic.

Currently supported runners:

| Runner | Env value | Requires | Best for |
|---|---|---|---|
| **nsjail** | `nsjail` (default) | Verified namespace/mount security profile | Namespace-isolated execution |
| **chroot** | `chroot` | No special capabilities | Kubernetes (baseline PodSecurity), restricted environments |

Adding a new runner requires implementing `setup_sandbox(root_dir)` and `run_command(sandbox, command, timeout, env, cwd) -> ExecResult`, then registering it in `manager.py`.

## Filesystem layout (both runners)

Each sandbox root directory (`<sandbox_base_dir>/<uuid>/`) has:
- `home/` — the user-writable workspace, mounted/chrooted as `/home` inside the sandbox
- `tmp/` — (chroot only) cleaned between commands

System binaries (`/usr`, `/lib`, `/bin`, etc.) are provided via bind mounts (nsjail) or copies/symlinks (chroot).

## Shared resources

An optional host directory (`AGENTJAIL_RESOURCES_DIR`, default `/var/lib/agentjail/resources`) is bind-mounted read-only at `/resources` inside every sandbox. All sandboxes share the same files — no copies are made. Host changes are visible immediately. If the directory doesn't exist, the mount is skipped.

### Scoping resources per sandbox

A sandbox may be created with a `resources` list of glob patterns, selecting which parts of that shared directory it can see. The default, `["*"]`, is everything — so a sandbox created without an opinion behaves exactly as before.

This lets one resources directory serve agents with different jobs: an assistant mounting `["assistant/**", "shared/**"]` and a protocol worker mounting `["protocols/**", "shared/**"]` read the same host directory but cannot see each other's material.

The selection is applied at **mount time** (`nsjail.py`), not by filtering the listing. `/resources` is a bind mount, so anything mounted is readable with `cat` whether or not a tool listed it — filtering the listing alone would hide files without protecting them. When patterns select only part of a directory, that directory is descended into and its selected entries are mounted individually at their usual paths; a fully-selected directory is mounted whole, keeping the flag count low.

`sandbox_resources` filters its listing by the same patterns when passed a `sandbox_id`, so agents are not told about files they cannot open.

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

## Execution lifecycle

The supervisor authenticates with a service bearer credential, creates/resolves
its authorized workspace, and acquires an exclusive lease. Commands carry that
workspace's token and receive a deadline no later than its remaining lease.
Renewal updates admission for future commands. Stop/expiry invalidates the token
before cancelling registered tasks; reacquisition waits for prior cleanup before
issuing a new token. Stop and force removal therefore fence old execution before
reusing or deleting its files.

All runners use `sandbox/process.py` for POSIX process sessions, cancellation,
timeouts and bounded concurrent stdout/stderr draining. The runner task remains
registered until process cleanup finishes. Request disconnection and service
shutdown cancel that task through the same path. A global active-command limit
rejects work rather than retaining an unbounded queue.

The ASGI bearer middleware wraps REST, documentation and the mounted MCP app.
Only the fixed health response bypasses authentication. Lease tokens never enter
persistent state. This control plane trusts its authenticated supervisors; it
does not implement Vigil membership or organization authorization.
