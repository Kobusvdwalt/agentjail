# Plan 04: Enforce Maximum Bounds on Resource Limits

## Goal

Add upper-bound validation to `time_limit`, `memory_limit`, and `pids_limit` so API callers cannot request unbounded resources. Be generous with the caps.

## Why

Currently, API callers can set arbitrarily high values for resource limits via `SandboxCreateRequest`, `SandboxRunRequest`, `ExecRequest`, and MCP tools. For example, `time_limit=999999` lets a sandbox run for 11+ days, and `memory_limit=999999` allows ~1 TB of virtual memory.

## Proposed Maximum Values

| Limit | Default | Maximum | Rationale |
|---|---|---|---|
| `time_limit` | 30s | 3600 (1 hour) | Generous for long builds/installs |
| `memory_limit` | 256 MB | 8192 (8 GB) | Generous for data processing |
| `pids_limit` | 64 | 1024 | Generous for parallel builds |

## Files to Change

### 1. `service-agentjail/src/agentjail/config.py`

Add max constants to `AgentjailSettings`:

```python
class AgentjailSettings(BaseSettings):
    # ... existing fields ...

    # Maximum allowed values (API callers cannot exceed these)
    max_time_limit: int = 3600
    max_memory_limit: int = 8192
    max_pids_limit: int = 1024
```

These become configurable via env vars (`AGENTJAIL_MAX_TIME_LIMIT`, etc.) or the YAML config file (Plan 05).

### 2. `service-agentjail/src/agentjail/sandbox/models.py`

Add a validator to `SandboxConfig` is one option, but since the model doesn't know about settings, it's better to validate in the manager.

### 3. `service-agentjail/src/agentjail/sandbox/manager.py`

Add a private method to clamp/validate limits, and call it in both `sandbox_run()` and `sandbox_create()`:

```python
def _validate_limits(
    self,
    time_limit: int | None,
    memory_limit: int | None,
    pids_limit: int | None,
) -> tuple[int, int, int]:
    tl = min(time_limit or self.settings.default_time_limit, self.settings.max_time_limit)
    ml = min(memory_limit or self.settings.default_memory_limit, self.settings.max_memory_limit)
    pl = min(pids_limit or self.settings.default_pids_limit, self.settings.max_pids_limit)
    return tl, ml, pl
```

Use it in `sandbox_run()`:
```python
async def sandbox_run(self, command, time_limit=None, memory_limit=None, env=None):
    tl, ml, _ = self._validate_limits(time_limit, memory_limit, None)
    # ... use tl, ml instead of raw values ...
```

Use it in `sandbox_create()`:
```python
async def sandbox_create(self, ..., time_limit=None, memory_limit=None, pids_limit=None, ...):
    tl, ml, pl = self._validate_limits(time_limit, memory_limit, pids_limit)
    # ... use tl, ml, pl in SandboxConfig ...
```

### 4. `service-agentjail/src/agentjail/api/routes/exec.py`

Also validate `timeout` in exec/shell requests. The `ExecRequest.timeout` and `ShellRequest.timeout` are passed directly to `nsjail.run_command()`. The manager's `sandbox_exec` should clamp this:

In `manager.py`, `sandbox_exec()`:
```python
effective_timeout = min(timeout, self.settings.max_time_limit) if timeout else None
```

### 5. MCP tools in `service-agentjail/src/agentjail/mcp/server.py`

No changes needed — MCP tools call the same manager methods which will now enforce bounds.

## Behaviour

- Values **above** the max are silently clamped to the max (not rejected). This avoids breaking clients that pass high defaults.
- Values **not specified** (None) use the default from settings.
- Minimum values are implicitly 1 (Pydantic int field, no need for explicit check since nsjail handles 0 gracefully).

## Verification

```bash
docker compose up --build

# Try to create a sandbox with huge limits:
curl -s -X POST http://localhost:8000/api/v1/sandbox \
  -H 'Content-Type: application/json' \
  -d '{"time_limit": 999999, "memory_limit": 999999, "pids_limit": 999999}' | jq .config

# Expected: time_limit=3600, memory_limit=8192, pids_limit=1024
```

## Reference

- `service-agentjail/src/agentjail/config.py` — where defaults live
- `service-agentjail/src/agentjail/sandbox/manager.py` — `sandbox_run()` line 63-65 and `sandbox_create()` line 97-101 build `SandboxConfig`
- `service-agentjail/src/agentjail/sandbox/nsjail.py` — `_build_args()` reads limits from `sandbox.config`
- `docs/DESIGN.md` — "Sandbox isolation guarantees" section lists current defaults
