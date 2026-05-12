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
docker compose up --build
```

The server starts on `http://localhost:8000`.

### MCP (for Claude / Cursor)

Point your MCP client at `http://localhost:8000/mcp`. The server exposes 7 tools:

| Tool | Description |
|---|---|
| `sandbox_create` | Create a persistent sandbox (returns an ID) |
| `sandbox_inspect` | Get sandbox details |
| `sandbox_stop` | Stop a sandbox |
| `sandbox_remove` | Remove a sandbox and its files |
| `sandbox_shell` | Execute a shell command (pipes, redirects, etc.) |
| `sandbox_download` | Prepare a file for download (returns a URL to fetch it) |
| `sandbox_resources` | List shared resource files and discovered Agent Skills |

### REST API

```bash
# Ephemeral — run a command and throw away the sandbox
curl -X POST http://localhost:8000/api/v1/sandbox/run \
  -H 'Content-Type: application/json' \
  -d '{"command": "echo hello world"}'

# Persistent — create a sandbox, run commands, inspect files
SANDBOX_ID=$(curl -s -X POST http://localhost:8000/api/v1/sandbox \
  -H 'Content-Type: application/json' \
  -d '{"name": "my-sandbox"}' | jq -r .id)

# Run a shell command
curl -X POST http://localhost:8000/api/v1/sandbox/$SANDBOX_ID/shell \
  -H 'Content-Type: application/json' \
  -d '{"command": "python3 -c \"print(42 ** 10)\""}'

# Upload a file
curl -X POST http://localhost:8000/api/v1/sandbox/$SANDBOX_ID/fs/upload \
  -F 'file=@hello.py'

# Execute it
curl -X POST http://localhost:8000/api/v1/sandbox/$SANDBOX_ID/shell \
  -H 'Content-Type: application/json' \
  -d '{"command": "python3 /home/uploads/hello.py"}'

# Prepare a file for download (returns a URL)
curl -X POST "http://localhost:8000/api/v1/sandbox/$SANDBOX_ID/download?path=/home/uploads/hello.py"

# Clean up
curl -X POST http://localhost:8000/api/v1/sandbox/$SANDBOX_ID/stop
curl -X DELETE http://localhost:8000/api/v1/sandbox/$SANDBOX_ID
```

### Full REST API Surface

```
POST   /api/v1/sandbox               — create persistent sandbox
GET    /api/v1/sandbox/{id}          — inspect sandbox
POST   /api/v1/sandbox/{id}/stop     — mark sandbox stopped
DELETE /api/v1/sandbox/{id}          — remove sandbox (force=true to remove running)
POST   /api/v1/sandbox/{id}/shell   — run shell command (via /bin/sh -c)
POST   /api/v1/sandbox/{id}/fs/upload   — upload a file (multipart)
GET    /api/v1/sandbox/{id}/fs/download?path= — download a file directly
POST   /api/v1/sandbox/{id}/download?path=    — prepare file for download (returns URL)
GET    /api/v1/sandbox/{id}/downloads/{name}  — fetch a prepared download
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
| `AGENTJAIL_HOST` | `0.0.0.0` | Listen address |
| `AGENTJAIL_PORT` | `8000` | Listen port |
| `AGENTJAIL_SANDBOX_BASE_DIR` | `/var/lib/agentjail/sandboxes` | Where sandbox directories are stored |
| `AGENTJAIL_STATE_FILE` | `/var/lib/agentjail/state.json` | Path to the JSON state file |
| `AGENTJAIL_NSJAIL_BIN` | `nsjail` | Path to the nsjail binary |
| `AGENTJAIL_RESOURCES_DIR` | `/var/lib/agentjail/resources` | Read-only files injected into every sandbox at `/resources` |
| `AGENTJAIL_DEFAULT_TIME_LIMIT` | `30` | Default time limit (seconds) |
| `AGENTJAIL_DEFAULT_MEMORY_LIMIT` | `256` | Default memory limit (MB) |
| `AGENTJAIL_DEFAULT_PIDS_LIMIT` | `64` | Default PID limit |

## Docker Requirements

agentjail requires elevated Docker privileges for nsjail to create Linux namespaces:

```yaml
cap_add:
  - SYS_ADMIN
security_opt:
  - apparmor=unconfined
  - seccomp=unconfined
```

These privileges are for the **container** — nsjail then uses them to create unprivileged sandboxes inside the container. The sandboxed processes themselves have no special capabilities.

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
