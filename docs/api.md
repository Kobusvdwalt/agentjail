# API Reference

## REST API

```
POST   /api/v1/sandbox              — create persistent sandbox
GET    /api/v1/sandbox/{id}         — inspect sandbox
POST   /api/v1/sandbox/{id}/stop    — mark sandbox stopped
DELETE /api/v1/sandbox/{id}         — remove sandbox (force=true to remove running)
POST   /api/v1/sandbox/{id}/shell  — run shell command (via /bin/sh -c)
POST   /api/v1/sandbox/{id}/fs/upload   — upload a file (multipart)
GET    /api/v1/sandbox/{id}/fs/download?path= — download a file directly
POST   /api/v1/sandbox/{id}/download?path=    — prepare file for download (returns URL)
GET    /api/v1/sandbox/{id}/downloads/{name}  — fetch a prepared download
GET    /api/v1/state                — raw state file
```

## MCP Tools (7)

| Tool | Description |
|---|---|
| `sandbox_create` | Create a persistent sandbox (returns an ID) |
| `sandbox_inspect` | Get sandbox details |
| `sandbox_stop` | Stop a sandbox |
| `sandbox_remove` | Remove a sandbox and its files |
| `sandbox_shell` | Execute a shell command (pipes, redirects, etc.) |
| `sandbox_download` | Prepare a file for download — `path` is an absolute path inside the sandbox (e.g. `/home/output.csv`). Copies to a downloads folder with a UUID name, returns a URL |
| `sandbox_resources` | List shared read-only resource files and discovered Agent Skills (parses `SKILL.md` frontmatter). `max_depth` controls directory scan depth (default 2) |

### Tool Filtering

Set `AGENTJAIL_MCP_TOOLS` to a JSON list of tool names to expose only a subset of tools. When unset, all tools are enabled.

```bash
# Only expose shell and download — agent cannot create/remove sandboxes
AGENTJAIL_MCP_TOOLS='["sandbox_shell", "sandbox_download", "sandbox_resources"]'
```

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
