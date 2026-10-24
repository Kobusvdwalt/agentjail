```
 ██╗██╗ ██╗      █████╗  ██████╗ ███████╗███╗   ██╗████████╗         ██╗ █████╗ ██╗██╗     
██╔╝╚██╗╚██╗    ██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝         ██║██╔══██╗██║██║     
██║  ██║ ██║    ███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║            ██║███████║██║██║     
██║  ██║ ██║    ██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║       ██   ██║██╔══██║██║██║     
╚██╗██╔╝██╔╝    ██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║       ╚█████╔╝██║  ██║██║███████╗
 ╚═╝╚═╝ ╚═╝     ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝        ╚════╝ ╚═╝  ╚═╝╚═╝╚══════╝
```
Sandboxed command execution for AI agents. Give your agent a shell — without giving it the keys to your machine.

agentjail provides isolated Linux environments via [MCP](https://modelcontextprotocol.io/) (for Claude, Cursor, etc.) and a REST API, using [nsjail](https://github.com/google/nsjail) for kernel-level process isolation. Each command runs in its own namespace-isolated sandbox with restricted filesystem access, resource limits, and no network by default.

## Why

AI agents that can run code are powerful, but letting them execute arbitrary commands on your host is a terrible idea. agentjail solves this by giving agents a sandboxed environment where they can:

- Run shell commands, scripts, and pipelines
- Install packages and build projects
- Read and write files in an isolated workspace
- Optionally access the network (for `pip install`, `curl`, etc.)

...all without being able to touch your host filesystem, read your environment variables, or fork-bomb your machine.

## How It Works

```
┌──────────────────────────────────────────┐
│  Your AI Agent (Claude, Cursor, etc.)    │
│  Connects via MCP or REST API            │
└────────────┬─────────────────────────────┘
             │
             ▼
┌──────────────────────────────────────────┐
│  agentjail server (FastAPI + FastMCP)    │
│  Single process, port 8000               │
│  /mcp — MCP transport (HTTP/SSE)         │
│  /api/v1/... — REST API                  │
├──────────────────────────────────────────┤
│  For each command:                       │
│  spawns nsjail ──► isolated process      │
│                                          │
│  ┌────────────────────────────────────┐  │
│  │  nsjail sandbox                    │  │
│  │  • PID namespace (process isolation│) │
│  │  • Network namespace (no net)      │  │
│  │  • Mount namespace (FS isolation)  │  │
│  │  • User namespace (uid 1000)       │  │
│  │  • IPC/UTS namespace               │  │
│  │  • Resource limits (CPU/mem/pids)  │  │
│  │  • Read-only: /usr /lib /bin /etc  │  │
│  │  • Read-only: /resources (shared)   │  │
│  │  • Read-write: /home (sandbox dir) │  │
│  │  • Ephemeral: /tmp /dev            │  │
│  └────────────────────────────────────┘  │
└──────────────────────────────────────────┘
```

No long-running daemon — each command spawns a fresh nsjail process, executes, and exits. A "running" sandbox just means it can accept commands, not that it has a live process.

## Quick Start

```bash
git clone https://github.com/your-org/get-agentjail.git
cd get-agentjail
export AGENTJAIL_API_TOKEN="$(openssl rand -hex 32)"
docker compose up --build
```

The server starts on `http://localhost:8000`. All REST and MCP requests require
`Authorization: Bearer <AGENTJAIL_API_TOKEN>`. The service refuses to start without
a token of at least 32 characters. Only `GET /health` is public. Use TLS outside
loopback development and keep this administrative credential out of sandbox files,
command environments and model-visible tools. This is a breaking change for
existing unauthenticated clients; see [the API migration](docs/api.md#authentication-and-migration).

Commands require a renewable, workspace-scoped execution lease. Stop, expiry,
request disconnect and shutdown cancel active commands and wait for process
cleanup. Captured output and concurrent execution are bounded. Files survive stop
and lease reacquisition; deleting a workspace still deletes its files.

### MCP (for Claude / Cursor)

Point your MCP client at `http://localhost:8000/mcp`. Configure the bearer header in your client. The server exposes 10 tools:

| Tool | Description |
|---|---|
| `sandbox_create` | Create a persistent sandbox (returns an ID) |
| `sandbox_inspect` | Get sandbox details |
| `sandbox_stop` | Stop a sandbox |
| `sandbox_remove` | Remove a sandbox and its files |
| `sandbox_acquire_lease` | Acquire exclusive execution ownership or resume a stopped workspace |
| `sandbox_renew_lease` | Renew an unexpired lease |
| `sandbox_shell` | Execute a shell command with its `lease_token` |
| `sandbox_host_file` | Prepare a file for host retrieval (returns a URL to fetch it) |
| `sandbox_read_media` | Read image/audio files and return MCP media content |
| `sandbox_resources` | List shared resource files and discovered Agent Skills — pass `sandbox_id` to scope the listing to that sandbox |

To expose only a subset of tools, set `AGENTJAIL_MCP_TOOLS` to a JSON list:

```bash
# Agent can only run commands and list resources — no sandbox lifecycle control
AGENTJAIL_MCP_TOOLS='["sandbox_shell", "sandbox_host_file", "sandbox_resources"]'
```

### REST API

```bash
# Persistent — create a sandbox, run commands, inspect files
SANDBOX_ID=$(curl -H "Authorization: Bearer $AGENTJAIL_API_TOKEN" -s -X POST http://localhost:8000/api/v1/sandbox \
  -H 'Content-Type: application/json' \
  -d '{"name": "my-sandbox"}' | jq -r .id)

# Acquire exclusive execution ownership (renew before expiry for later commands)
LEASE_TOKEN=$(curl -H "Authorization: Bearer $AGENTJAIL_API_TOKEN" -s -X POST \
  "http://localhost:8000/api/v1/sandbox/$SANDBOX_ID/lease" \
  -H 'Content-Type: application/json' -d '{"lease_seconds": 120}' | jq -r .lease_token)

# Run a shell command
curl -H "Authorization: Bearer $AGENTJAIL_API_TOKEN" -X POST http://localhost:8000/api/v1/sandbox/$SANDBOX_ID/shell \
  -H 'Content-Type: application/json' \
  -d "$(jq -n --arg lease "$LEASE_TOKEN" '{command: "printf hello", lease_token: $lease}')"

# Upload a file
curl -H "Authorization: Bearer $AGENTJAIL_API_TOKEN" -X POST http://localhost:8000/api/v1/sandbox/$SANDBOX_ID/fs/upload \
  -F 'file=@hello.py'

# Execute it
curl -H "Authorization: Bearer $AGENTJAIL_API_TOKEN" -X POST http://localhost:8000/api/v1/sandbox/$SANDBOX_ID/shell \
  -H 'Content-Type: application/json' \
  -d "$(jq -n --arg lease "$LEASE_TOKEN" '{command: "python3 /uploads/hello.py", lease_token: $lease}')"

# Prepare a file for host retrieval (returns a URL)
curl -H "Authorization: Bearer $AGENTJAIL_API_TOKEN" -X POST "http://localhost:8000/api/v1/sandbox/$SANDBOX_ID/host?path=/uploads/hello.py"

# Clean up
curl -H "Authorization: Bearer $AGENTJAIL_API_TOKEN" -X POST http://localhost:8000/api/v1/sandbox/$SANDBOX_ID/stop
curl -H "Authorization: Bearer $AGENTJAIL_API_TOKEN" -X DELETE http://localhost:8000/api/v1/sandbox/$SANDBOX_ID
```

### Full REST API Surface

```
POST   /api/v1/sandbox               — create persistent sandbox
GET    /api/v1/sandbox/{id}          — inspect sandbox
POST   /api/v1/sandbox/{id}/stop     — revoke execution ownership and wait for command termination
DELETE /api/v1/sandbox/{id}          — remove sandbox (force=true to remove running)
POST   /api/v1/sandbox/{id}/lease — acquire/resume execution ownership
POST   /api/v1/sandbox/{id}/lease/renew — renew execution ownership
POST   /api/v1/sandbox/{id}/shell   — run shell command (via /bin/sh -c)
POST   /api/v1/sandbox/{id}/fs/upload   — upload a file (multipart)
GET    /api/v1/sandbox/{id}/fs/download?path= — download a file directly
POST   /api/v1/sandbox/{id}/host?path=        — prepare file for host retrieval (returns URL)
GET    /api/v1/sandbox/{id}/hosted/{name}     — fetch a prepared hosted file
GET    /api/v1/state                 — raw state file
```

## Sandbox Options

| Option | Default | Description |
|---|---|---|
| `name` | `null` | Human-readable sandbox name |
| `time_limit` | `30` | Max seconds per command |
| `memory_limit` | `256` | Max virtual memory in MB |
| `pids_limit` | `64` | Max concurrent processes |
| `network` | `false` | Enable network access |
| `env` | `{}` | Environment variables passed into the sandbox |
| `cwd` | `/home` | Working directory inside the sandbox |
| `resources` | `["*"]` | Glob patterns for which shared resources are mounted at `/resources` |

### Scoping resources per sandbox

One resources directory can serve agents with different jobs. Pass glob patterns
(relative to the resources root) and the sandbox sees only those:

```bash
# The assistant's own material plus the shared set
curl -H "Authorization: Bearer $AGENTJAIL_API_TOKEN" -X POST localhost:8000/api/v1/sandbox \
  -H 'Content-Type: application/json' \
  -d '{"name": "assistant", "resources": ["assistant/**", "shared/**"]}'

# A protocol worker, same directory, different view
curl -H "Authorization: Bearer $AGENTJAIL_API_TOKEN" -X POST localhost:8000/api/v1/sandbox \
  -H 'Content-Type: application/json' \
  -d '{"name": "protocols", "resources": ["protocols/**", "shared/**"]}'
```

`*` matches within one path segment, `**` across segments, and a bare `*` means
everything (the default). Pass `[]` for no resources at all.

Unselected files are **not mounted**, so they cannot be read from inside the
sandbox — this is a mount boundary, not a filtered listing. Note that it
separates agent roles, not API callers: any caller can create a sandbox with
`["*"]`, so keep genuinely sensitive material out of the resources directory.

## Isolation Guarantees

Every command runs inside nsjail with:

- **PID namespace** — can't see or signal other processes
- **Network namespace** — no network by default (opt-in with `network: true`)
- **Mount namespace** — isolated filesystem view
- **User namespace** — runs as uid/gid 1000, no root capabilities
- **IPC namespace** — isolated shared memory / semaphores
- **UTS namespace** — isolated hostname
- **Resource limits** — memory, CPU, PIDs, file size, open files all capped
- **Read-only system** — `/usr`, `/lib`, `/bin`, `/sbin`, `/etc` are read-only
- **Ephemeral /tmp** — 64MB tmpfs, destroyed after each command
- **Path traversal protection** — filesystem API prevents escaping the sandbox root

## Configuration

Settings are configurable via environment variables (prefix `AGENTJAIL_`):

| Variable | Default | Description |
|---|---|---|
| `AGENTJAIL_API_TOKEN` | required | Random service bearer credential, at least 32 characters |
| `AGENTJAIL_MAX_OUTPUT_BYTES` | `65536` | Retained raw bytes per output stream, range 1–1048576 |
| `AGENTJAIL_MAX_ACTIVE_COMMANDS` | `8` | Active command limit, range 1–128 |
| `AGENTJAIL_HOST` | `0.0.0.0` | Listen address |
| `AGENTJAIL_PORT` | `8000` | Listen port |
| `AGENTJAIL_RUNNER` | `nsjail` | Sandbox runner: `nsjail`, `chroot`, or `bare` |
| `AGENTJAIL_SANDBOX_BASE_DIR` | `/var/lib/agentjail/sandboxes` | Where sandbox directories are stored |
| `AGENTJAIL_STATE_FILE` | `/var/lib/agentjail/state.json` | Path to the JSON state file |
| `AGENTJAIL_NSJAIL_BIN` | `nsjail` | Path to the nsjail binary |
| `AGENTJAIL_RESOURCES_DIR` | `/var/lib/agentjail/resources` | Read-only files injected into every sandbox at `/resources` |
| `AGENTJAIL_DEFAULT_TIME_LIMIT` | `30` | Default time limit (seconds) |
| `AGENTJAIL_DEFAULT_MEMORY_LIMIT` | `256` | Default memory limit (MB) |
| `AGENTJAIL_DEFAULT_PIDS_LIMIT` | `64` | Default PID limit |

## Execution ownership

Leases last 1–300 seconds. Every shell request includes its `lease_token`; tokens
are bound to one workspace and never appear in state or inspection responses.
An active lease cannot be taken over. Stop and expiry revoke it, and reacquiring
returns a different token. Service restart invalidates all leases while retaining
files on the configured storage. A single service process must own each state
file; file locking does not coordinate live execution across processes.

All authenticated callers are trusted supervisors with access to the entire
control plane. Leases are execution fencing, not organization authorization.
Vigil must resolve organization membership and workspace ownership in its trusted
API/worker before making these calls. Never give a model the service credential
or direct access to these administrative MCP tools.

## Docker Requirements

The example Compose profile grants the following permissions for namespace creation.
The minimum working profile depends on the runtime; verify it before deployment:

```yaml
cap_add:
  - SYS_ADMIN
security_opt:
  - apparmor=unconfined
  - seccomp=unconfined
```

These privileges are for the **container** — nsjail then uses them to create unprivileged sandboxes inside the container. The sandboxed processes themselves have no special capabilities.

### Running without privileges (bare runner)

For trusted local development only, the **bare runner** avoids namespace setup.
It does not isolate untrusted commands; do not use it as a production fallback:

```yaml
env:
  - name: AGENTJAIL_RUNNER
    value: "bare"
```

⚠️ The bare runner provides **no isolation** — commands run directly as the service user. Use only for prototyping or when the pod itself is your isolation boundary. See `docs/runners.md` for details.

## Extending the Base Image

The production image ships a self-contained `/opt/agentjail` tree. Bring it into **any** image with a single `COPY --from` — like uv does:

```dockerfile
FROM python:3.12-slim

# Bring in agentjail + nsjail (fully self-contained — no extra deps needed)
COPY --from=agentjail:latest /opt/agentjail /opt/agentjail
```

Anything installed under `/usr`, `/lib`, `/bin`, etc. is automatically available inside sandboxes (these paths are bind-mounted read-only). See `docs/examples/` for more examples (Python, Go, Bun).

## Development

```bash
# Start with hot-reload
docker compose up --build --watch

# Source files sync into the container automatically
# pyproject.toml changes trigger a rebuild
```

The dev setup uses `docker compose watch` — edit files locally and the container reloads automatically.

## Tech Stack

- **Python 3.14** with **uv** — server runtime and package management
- **FastMCP** — MCP server (HTTP/SSE transport)
- **FastAPI** + **uvicorn** — REST API
- **nsjail** — Linux sandbox isolation (namespace-based)
- **Pydantic** — data models and config
- **filelock** — thread-safe state file management

## License

MIT
