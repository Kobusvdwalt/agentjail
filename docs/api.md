# API Reference

## REST API

```
POST   /api/v1/sandbox              — create persistent sandbox
GET    /api/v1/sandbox/{id}         — inspect sandbox
POST   /api/v1/sandbox/{id}/stop    — revoke its lease and wait for active commands to terminate
DELETE /api/v1/sandbox/{id}         — remove sandbox (force=true to remove running)
POST   /api/v1/sandbox/{id}/lease — acquire/resume exclusive execution ownership
POST   /api/v1/sandbox/{id}/lease/renew — renew current execution ownership
POST   /api/v1/sandbox/{id}/shell  — run shell command (via /bin/sh -c)
POST   /api/v1/sandbox/{id}/fs/upload   — upload a file (multipart)
GET    /api/v1/sandbox/{id}/fs/download?path= — download a file directly
POST   /api/v1/sandbox/{id}/host?path=        — prepare file for host retrieval (returns URL)
GET    /api/v1/sandbox/{id}/hosted/{name}     — fetch a prepared hosted file
GET    /api/v1/state                — raw state file
```

## MCP Tools (10)

| Tool | Description |
|---|---|
| `sandbox_create` | Create a persistent sandbox (returns an ID) |
| `sandbox_inspect` | Get sandbox details |
| `sandbox_stop` | Stop a sandbox |
| `sandbox_remove` | Remove a sandbox and its files |
| `sandbox_acquire_lease` | Acquire exclusive execution ownership or resume a stopped workspace |
| `sandbox_renew_lease` | Renew the current execution lease |
| `sandbox_shell` | Execute with required `lease_token` |
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

## Authentication and migration

This change breaks existing unauthenticated REST/MCP clients and shell callers.
Set `AGENTJAIL_API_TOKEN` to a randomly generated value of at least 32 characters
and send `Authorization: Bearer <token>` on every request, including downloads,
state, OpenAPI and MCP. Only `GET /health` is public; it returns `{"status":"ok"}`.
Missing or incorrect credentials return 401 with `WWW-Authenticate: Bearer`.
The OpenAPI schema advertises the bearer requirement. Terminate TLS before this
service in production. Never put tokens in URLs or public hosted-file links.

All holders of the service credential are trusted supervisors. It does not
represent a user or organization: tenant authorization belongs in the caller's
trusted API. Publish artifacts through a separate authorized hosting path rather
than sharing this credential. Update old clients before rolling out the service;
there is no unauthenticated compatibility mode.

## Execution lease contract

`POST /sandbox/{id}/lease` accepts `{"lease_seconds":120}` (1–300, default 120)
and returns `{"lease_token":"<opaque>","lease_seconds":120}`. It resumes a stopped
workspace using its existing files. An unexpired lease prevents another acquire
with HTTP 409; it cannot be forcibly replaced by acquiring again.

`POST /sandbox/{id}/lease/renew` accepts the current `lease_token` and a new
`lease_seconds`. It returns the same token and new duration. An expired or revoked
lease cannot renew. Renew before expiry; renewal affects future commands, and
does not extend a command's already admitted deadline.

`POST /sandbox/{id}/shell` requires `{"command":"...","lease_token":"..."}` and
accepts a positive integer `timeout` in seconds. A command runs only while its
workspace is running and its token is current. Its timeout is capped to the
configured maximum and the remaining lease duration. Wrong-workspace, expired
and revoked leases return 409; missing tokens or nonpositive limits return 422.
Service-wide execution saturation returns 429 rather than queueing commands.

The shell response preserves `exit_code`, `stdout`, `stderr` and `timed_out`,
and adds `killed`, `stdout_truncated` and `stderr_truncated`. The output cap retains
the last configured number of raw bytes per stream, decoding invalid UTF-8 with
replacement. Stop/expiry cancellation produces `killed: true` for a connected
caller. A disconnected caller receives no usable result; server cleanup still runs.

Stop first closes admission and revokes its lease, then waits for registered
commands to terminate. Removal also waits before deleting files. HTTP disconnect
cancels that request's command. Lease expiry provides independent server cleanup
when the worker disappears without delivering cancellation. Service restart drops
all in-memory lease authority; acquire a new lease to recover stored files.
Tokens are not persisted or included in sandbox/state responses.

MCP adds `sandbox_acquire_lease` and `sandbox_renew_lease`, and `sandbox_shell` gains
a required `lease_token` argument. Do not expose administrative MCP tools directly
to Vigil models. Tool allowlists do not enforce tenant authorization.
