# API Reference

## REST API

```
POST   /api/v1/sandbox/run          — ephemeral: run command, return result, cleanup
POST   /api/v1/sandbox              — create persistent sandbox
GET    /api/v1/sandbox              — list sandboxes
GET    /api/v1/sandbox/{id}         — inspect sandbox
POST   /api/v1/sandbox/{id}/stop    — mark sandbox stopped
DELETE /api/v1/sandbox/{id}         — remove sandbox (force=true to remove running)
POST   /api/v1/sandbox/{id}/shell  — run shell command (via /bin/sh -c)
GET    /api/v1/sandbox/{id}/fs/read?path=
POST   /api/v1/sandbox/{id}/fs/write
GET    /api/v1/sandbox/{id}/fs/list?path=
POST   /api/v1/sandbox/{id}/fs/mkdir
DELETE /api/v1/sandbox/{id}/fs?path=
GET    /api/v1/sandbox/{id}/fs/stat?path=
GET    /api/v1/state                — raw state file
```

## MCP Tools (13)

| Tool | Description |
|---|---|
| `sandbox_run` | Ephemeral: run a command, get output, sandbox is destroyed |
| `sandbox_create` | Create a persistent sandbox (returns an ID) |
| `sandbox_list` | List all sandboxes |
| `sandbox_inspect` | Get sandbox details |
| `sandbox_stop` | Stop a sandbox |
| `sandbox_remove` | Remove a sandbox and its files |
| `sandbox_shell` | Execute a shell command (pipes, redirects, etc.) |
| `sandbox_fs_read` | Read a file from the sandbox |
| `sandbox_fs_write` | Write a file to the sandbox |
| `sandbox_fs_list` | List directory contents |
| `sandbox_fs_mkdir` | Create directories |
| `sandbox_fs_remove` | Remove files or directories |
| `sandbox_fs_stat` | Get file metadata |

## Sandbox Options

| Option | Default | Description |
|---|---|---|
| `name` | `null` | Human-readable sandbox name |
| `time_limit` | `30` | Max seconds per command |
| `memory_limit` | `256` | Max virtual memory in MB |
| `pids_limit` | `64` | Max concurrent processes |
| `network` | `false` | Enable network access (nsjail only) |
| `env` | `{}` | Environment variables passed into the sandbox |
| `cwd` | `/home` | Working directory inside the sandbox |
