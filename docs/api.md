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
POST   /api/v1/sandbox/{id}/host?path=        — prepare file for host retrieval (returns URL)
GET    /api/v1/sandbox/{id}/hosted/{name}     — fetch a prepared hosted file
GET    /api/v1/state                — raw state file
```

## MCP Tools (8)

| Tool | Description |
|---|---|
| `sandbox_create` | Create a persistent sandbox (returns an ID) |
| `sandbox_inspect` | Get sandbox details |
| `sandbox_stop` | Stop a sandbox |
| `sandbox_remove` | Remove a sandbox and its files |
| `sandbox_shell` | Execute a shell command (pipes, redirects, etc.) |
| `sandbox_host_file` | Prepare a file for host retrieval — `path` is an absolute path inside the sandbox (e.g. `/home/output.csv`). Copies to a hosted folder with a UUID name, returns a URL |
| `sandbox_read_media` | Read an image or audio file and return MCP-compliant `ImageContent` (for `image/*`) or `AudioContent` (for `audio/*`) with base64-encoded data — lets agents understand visual/audio semantics directly |
| `sandbox_resources` | List shared read-only resource files and discovered Agent Skills (parses `SKILL.md` frontmatter). `max_depth` controls directory scan depth (default 2); `sandbox_id` scopes the listing to what that sandbox can actually see |

### Tool Filtering

Set `AGENTJAIL_MCP_TOOLS` to a JSON list of tool names to expose only a subset of tools. When unset, all tools are enabled.

```bash
# Only expose shell and hosted-file prep — agent cannot create/remove sandboxes
AGENTJAIL_MCP_TOOLS='["sandbox_shell", "sandbox_host_file", "sandbox_resources"]'
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
| `resources` | `["*"]` | Glob patterns selecting which shared resources are mounted at `/resources` |

### Scoping resources per sandbox

`resources` takes a list of glob patterns matched against paths relative to the
resources root. Omit it for everything; pass `[]` for nothing.

```jsonc
// One agent sees its own resources plus the shared set…
{ "name": "assistant", "resources": ["assistant/**", "shared/**"] }

// …and another sees a different subset of the same directory.
{ "name": "protocols", "resources": ["protocols/**", "shared/**"] }
```

Pattern syntax follows the `.gitignore` intuition: `*` matches within a single
path segment, `**` matches across segments, and a bare `*` means everything.

This is enforced by the **mount**, not by filtering the listing — unselected
files are never bind-mounted into the sandbox, so they cannot be read with
`cat` or found with `find`. `sandbox_resources` filters to match when given a
`sandbox_id`, so the listing describes what is actually reachable.
