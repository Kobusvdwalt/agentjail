# Plan 05: Sandbox Count/Disk Limits and YAML Config File

## Goal

1. Add a YAML configuration file (`agentjail.yaml`) as the primary config mechanism
2. Enforce maximum sandbox count and total disk usage limits
3. Make all tunable settings configurable via the YAML file

## Why

- No limit on sandbox count or disk usage = trivial DoS
- Environment variables are awkward for complex config (lists, nested objects)
- Users extending the base image (Plan 02) need a clean way to customize settings

## Config File Design

### File location and loading order

1. `/etc/agentjail/agentjail.yaml` (default, baked into image)
2. `AGENTJAIL_CONFIG_FILE` env var override (for custom path)
3. Environment variables still override individual settings (highest priority)

Priority: **env vars > yaml > code defaults**

### Proposed `agentjail.yaml` schema

```yaml
# /etc/agentjail/agentjail.yaml

server:
  host: "0.0.0.0"
  port: 8000

sandbox:
  base_dir: /var/lib/agentjail/sandboxes
  state_file: /var/lib/agentjail/state.json
  nsjail_bin: nsjail

  # Default limits (applied when not specified per-sandbox)
  defaults:
    time_limit: 30        # seconds
    memory_limit: 256     # MB
    pids_limit: 64

  # Maximum allowed limits (API callers cannot exceed these)
  max:
    time_limit: 3600      # 1 hour
    memory_limit: 8192    # 8 GB
    pids_limit: 1024

  # Global limits
  limits:
    max_sandboxes: 50           # max concurrent sandboxes
    max_total_disk_mb: 10240    # 10 GB total across all sandboxes
    max_sandbox_disk_mb: 2048   # 2 GB per individual sandbox

  # Read-only bind mounts exposed inside sandboxes
  bind_mount_ro:
    - /usr
    - /lib
    - /lib64
    - /bin
    - /sbin
    - /etc
```

## Files to Change / Create

### 1. Create `service-agentjail/config/agentjail.yaml`

The default config file with sensible defaults (as shown above).

### 2. Update `service-agentjail/src/agentjail/config.py`

Add YAML loading and the new limit fields:

```python
import yaml
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentjailSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENTJAIL_")

    host: str = "0.0.0.0"
    port: int = 8000

    sandbox_base_dir: Path = Path("/var/lib/agentjail/sandboxes")
    state_file: Path = Path("/var/lib/agentjail/state.json")
    nsjail_bin: str = "nsjail"

    # Defaults
    default_time_limit: int = 30
    default_memory_limit: int = 256
    default_pids_limit: int = 64

    # Max bounds (Plan 04)
    max_time_limit: int = 3600
    max_memory_limit: int = 8192
    max_pids_limit: int = 1024

    # Global limits (new)
    max_sandboxes: int = 50
    max_total_disk_mb: int = 10240
    max_sandbox_disk_mb: int = 2048

    bind_mount_ro: list[str] = ["/usr", "/lib", "/lib64", "/bin", "/sbin", "/etc"]

    config_file: Path = Path("/etc/agentjail/agentjail.yaml")
```

Add a classmethod or factory function that loads the YAML file first, then lets env vars override:

```python
@classmethod
def from_config(cls) -> "AgentjailSettings":
    config_path = Path(os.environ.get("AGENTJAIL_CONFIG_FILE", "/etc/agentjail/agentjail.yaml"))
    overrides = {}
    if config_path.exists():
        with open(config_path) as f:
            raw = yaml.safe_load(f) or {}
        # Flatten nested YAML into the flat pydantic fields
        server = raw.get("server", {})
        sandbox = raw.get("sandbox", {})
        defaults = sandbox.get("defaults", {})
        maxes = sandbox.get("max", {})
        limits = sandbox.get("limits", {})

        if "host" in server: overrides["host"] = server["host"]
        if "port" in server: overrides["port"] = server["port"]
        if "base_dir" in sandbox: overrides["sandbox_base_dir"] = sandbox["base_dir"]
        if "state_file" in sandbox: overrides["state_file"] = sandbox["state_file"]
        if "nsjail_bin" in sandbox: overrides["nsjail_bin"] = sandbox["nsjail_bin"]
        if "time_limit" in defaults: overrides["default_time_limit"] = defaults["time_limit"]
        if "memory_limit" in defaults: overrides["default_memory_limit"] = defaults["memory_limit"]
        if "pids_limit" in defaults: overrides["default_pids_limit"] = defaults["pids_limit"]
        if "time_limit" in maxes: overrides["max_time_limit"] = maxes["time_limit"]
        if "memory_limit" in maxes: overrides["max_memory_limit"] = maxes["memory_limit"]
        if "pids_limit" in maxes: overrides["max_pids_limit"] = maxes["pids_limit"]
        if "max_sandboxes" in limits: overrides["max_sandboxes"] = limits["max_sandboxes"]
        if "max_total_disk_mb" in limits: overrides["max_total_disk_mb"] = limits["max_total_disk_mb"]
        if "max_sandbox_disk_mb" in limits: overrides["max_sandbox_disk_mb"] = limits["max_sandbox_disk_mb"]
        if "bind_mount_ro" in sandbox: overrides["bind_mount_ro"] = sandbox["bind_mount_ro"]

    return cls(**overrides)
```

Add `pyyaml` to dependencies in `pyproject.toml`.

### 3. Update `service-agentjail/src/agentjail/server.py`

Change `AgentjailSettings()` to `AgentjailSettings.from_config()`.

### 4. Update `service-agentjail/src/agentjail/sandbox/manager.py`

Add enforcement in `sandbox_create()`:

```python
async def sandbox_create(self, ...) -> SandboxState:
    # Check sandbox count limit
    current_count = len(self.state.read().sandboxes)
    if current_count >= self.settings.max_sandboxes:
        raise SandboxLimitReached(f"Maximum sandbox count ({self.settings.max_sandboxes}) reached")

    # Check total disk usage
    total_disk = self._get_total_disk_usage_mb()
    if total_disk >= self.settings.max_total_disk_mb:
        raise DiskLimitReached(f"Total disk usage ({total_disk}MB) exceeds limit ({self.settings.max_total_disk_mb}MB)")

    # ... rest of create logic ...
```

Add a helper for disk usage calculation:

```python
def _get_total_disk_usage_mb(self) -> int:
    """Calculate total disk usage of all sandbox directories in MB."""
    total = 0
    if self.settings.sandbox_base_dir.exists():
        for entry in self.settings.sandbox_base_dir.iterdir():
            if entry.is_dir():
                total += sum(f.stat().st_size for f in entry.rglob("*") if f.is_file())
    return total // (1024 * 1024)
```

Add per-sandbox disk limit enforcement in `sandbox_exec` / `sandbox_shell` (check after each command execution):

```python
async def sandbox_exec(self, sandbox_id, ...):
    sandbox = self._get_sandbox(sandbox_id, require_running=True)
    result = await self.nsjail.run_command(...)

    # Check per-sandbox disk usage after execution
    sandbox_disk_mb = self._get_sandbox_disk_usage_mb(sandbox.root_dir)
    if sandbox_disk_mb > self.settings.max_sandbox_disk_mb:
        # Don't kill the sandbox, but warn in stderr
        result.stderr += f"\n[agentjail] WARNING: Sandbox disk usage ({sandbox_disk_mb}MB) exceeds limit ({self.settings.max_sandbox_disk_mb}MB)"

    return result
```

Add new exception classes:

```python
class SandboxLimitReached(Exception):
    pass

class DiskLimitReached(Exception):
    pass
```

### 5. Update API routes to handle new exceptions

In `service-agentjail/src/agentjail/api/routes/sandbox.py`, catch `SandboxLimitReached` and `DiskLimitReached` and return HTTP 429 (Too Many Requests) or 507 (Insufficient Storage).

### 6. Update `pyproject.toml`

Add `pyyaml` to dependencies:
```toml
dependencies = [
    # ... existing ...
    "pyyaml>=6.0",
]
```

### 7. Update Dockerfiles

Copy the config file:
```dockerfile
COPY config/ /etc/agentjail/
```
This line already exists in both Dockerfiles, so `agentjail.yaml` placed in `config/` will be copied automatically.

## Verification

```bash
# Test sandbox count limit
for i in $(seq 1 55); do
  curl -s -X POST http://localhost:8000/api/v1/sandbox -H 'Content-Type: application/json' -d '{}'
done
# Expected: first 50 succeed, rest return 429

# Test custom config
# Modify _volumes/agentjail/ or mount a custom agentjail.yaml and restart
```

## Reference

- `service-agentjail/src/agentjail/config.py` — current settings class
- `service-agentjail/src/agentjail/server.py` — where settings are instantiated
- `service-agentjail/src/agentjail/sandbox/manager.py` — `sandbox_create()` and `sandbox_run()` are the entry points
- `docs/DESIGN.md` — "JSON state file" and "Sandbox isolation guarantees" sections
