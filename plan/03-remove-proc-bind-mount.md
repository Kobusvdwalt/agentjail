# Plan 03: Remove Host /proc Bind Mount

## Goal

Stop bind-mounting the host's `/proc` into sandboxes. Either mount nothing, or mount only specific safe pseudo-files needed for basic process functionality.

## Why

The current setup (`--disable_proc` + `--bindmount_ro /proc`) exposes the **host container's** `/proc` to every sandbox. This leaks:
- Environment variables of the agentjail server process (via `/proc/[pid]/environ`)
- Process list, memory maps, command lines of all processes in the container
- Mount topology (via `/proc/self/mountinfo`) revealing host paths
- Kernel version and system info

This is the most exploitable information leak for sandbox escape.

## Current Code

In `service-agentjail/src/agentjail/sandbox/nsjail.py`, `_build_args()` method, lines 73-74:
```python
args.append("--disable_proc")
args.extend(["--bindmount_ro", "/proc"])
```

And in `service-agentjail/config/nsjail_default.cfg`:
```
mount { dst: "/proc"  fstype: "proc"   rw: false }
```

## What to Change

### Option A: Mount nothing (recommended if sandboxed code doesn't need /proc)

In `service-agentjail/src/agentjail/sandbox/nsjail.py`, `_build_args()`:

```python
# Remove these two lines:
args.append("--disable_proc")
args.extend(["--bindmount_ro", "/proc"])

# Replace with just:
args.append("--disable_proc")
```

This means `/proc` won't exist inside the sandbox. Most command-line tools work fine without it. Things that will break:
- `ps`, `top`, `htop` (need `/proc` to list processes)
- Some Python stdlib calls like `os.cpu_count()` (returns `None` instead)
- `/proc/self/fd` tricks

### Option B: Mount a minimal set of safe files (if /proc is needed)

If some sandbox workloads genuinely need `/proc`, bind-mount only safe files:

```python
args.append("--disable_proc")
# Create a tmpfs at /proc, then bind-mount only safe entries
args.extend(["--mount", "none:/proc:tmpfs:size=4096"])
for safe in ["/proc/self/status", "/proc/self/stat", "/proc/cpuinfo", "/proc/meminfo", "/proc/version"]:
    if Path(safe).exists():
        args.extend(["--bindmount_ro", f"{safe}:{safe}"])
```

**Note:** This approach has complexity — nsjail may not support multiple mounts at the same destination well. Test thoroughly.

### Option C (simplest, recommended starting point): Just remove /proc entirely

```python
args.append("--disable_proc")
# That's it. No /proc inside sandbox.
```

### Also Update

1. `service-agentjail/config/nsjail_default.cfg` — remove the `/proc` mount line (this file is documentation, not runtime, but should stay in sync)
2. `docs/DESIGN.md` — update the "Bind-mount isolation" section. Currently says:
   > **Read-only** bind mount of `/proc` (host's `/proc`, since mounting fresh procfs is blocked by Docker)
   
   Change to reflect that `/proc` is no longer mounted, and why.

## Verification

```bash
docker compose up --build

# Create a sandbox and try to read /proc
curl -s -X POST http://localhost:8000/api/v1/sandbox -H 'Content-Type: application/json' -d '{}' | jq .id
# Use the returned ID:
curl -s -X POST http://localhost:8000/api/v1/sandbox/<ID>/shell -H 'Content-Type: application/json' -d '{"command": "ls /proc"}' | jq .
# Expected: error or empty — /proc should not exist

curl -s -X POST http://localhost:8000/api/v1/sandbox/<ID>/shell -H 'Content-Type: application/json' -d '{"command": "cat /proc/1/environ"}' | jq .
# Expected: error — must not be readable

# Verify basic commands still work:
curl -s -X POST http://localhost:8000/api/v1/sandbox/<ID>/shell -H 'Content-Type: application/json' -d '{"command": "echo hello && python3 -c \"print(1+1)\""}' | jq .
# Expected: hello\n2
```

## Reference

- `service-agentjail/src/agentjail/sandbox/nsjail.py` — `_build_args()` method, the two lines to change
- `service-agentjail/config/nsjail_default.cfg` — documentation-only config, update for consistency
- `docs/DESIGN.md` — "Bind-mount isolation" and "nsjail Configuration" sections describe current /proc setup
