# Sandbox Runners

agentjail supports pluggable sandbox runners. Set `AGENTJAIL_RUNNER` to select one.

---

## nsjail Runner (`AGENTJAIL_RUNNER=nsjail`)

Default runner. Requires elevated Docker privileges but provides the strongest isolation.

### Bind-mount isolation

Each sandbox gets:
- **Read-only** bind mounts of `/usr`, `/lib`, `/bin`, `/sbin`, `/etc` from the container (host binaries/libs)
- **Read-only** bind mount of `/resources` (shared resources directory, if configured)
- **Read-write** bind mount of `<root>/home` → `/home` inside the jail
- **tmpfs** at `/tmp` (64MB, ephemeral per command)
- **Read-only** bind mount of `/proc` (host's `/proc`, since mounting fresh procfs is blocked by Docker)
- **tmpfs** at `/dev`

### Isolation guarantees

- **PID namespace** (`CLONE_NEWPID`) — process isolation
- **Network namespace** (`CLONE_NEWNET`) — network disabled by default, opt-in via `network: true`
- **Mount namespace** (`CLONE_NEWNS`) — filesystem isolation
- **UTS namespace** (`CLONE_NEWUTS`) — hostname isolation
- **IPC namespace** (`CLONE_NEWIPC`) — IPC isolation
- **User namespace** (`CLONE_NEWUSER`) — runs as uid/gid 1000 inside the jail
- **Resource limits**:
  - `rlimit_as`: configurable memory limit (default 256MB)
  - `rlimit_nproc`: configurable PID limit (default 64)
  - `rlimit_fsize`: 50MB max file size
  - `rlimit_nofile`: 256 open file descriptors
  - `max_cpus`: 1
  - `time_limit`: configurable (default 30s)

### nsjail configuration flags

The nsjail command is built in `src/agentjail/sandbox/nsjail.py`. Key decisions:

| Flag | Value | Why |
|---|---|---|
| `--mode o` | standalone once | One command per nsjail invocation |
| `--rlimit_nproc` | configurable (default 64) | Used instead of `--pids_limit` which doesn't exist in the installed nsjail version |
| `--rlimit_fsize` | 50 (MB) | Default of 1MB was too small for pip wheels and uv temp files |
| `--rlimit_nofile` | 256 | Default of 32 was too few for package managers (uv, pip) |
| `--disable_proc` + `--bindmount_ro /proc` | bind host /proc | Docker blocks mounting fresh procfs due to overmounted paths (`/proc/kcore` etc.) |
| `--mount none:/tmp:tmpfs:size=67108864` | 64MB tmpfs | Default 4MB tmpfs was too small for package management temp files |
| `--disable_clone_newnet` | only when `network=True` | nsjail isolates network by default; flag is to *enable* networking |
| bind mount filtering | `Path.exists()` check | Skips mounts like `/lib64` that don't exist on Debian/slim images |

Commands are executed via `/bin/sh -c "<command>"` (full path required — nsjail uses `execve`, no PATH lookup).

---

## Chroot Runner (`AGENTJAIL_RUNNER=chroot`)

Designed for environments where `CAP_SYS_ADMIN` is blocked (e.g. Kubernetes with Kyverno baseline PodSecurity). No special Docker privileges required.

### How it works

1. **`setup_sandbox(root_dir)`**: Creates `home/` and `tmp/`. Copies `/usr` (using hardlinks where supported, falling back to full copy on overlayfs). Copies `/etc` (ignores unreadable files like shadow). Creates symlinks for `/bin`, `/sbin`, `/lib`, `/lib64` → their `/usr` equivalents.
2. **`run_command()`**: Builds a JSON config, invokes `_chroot_exec.py` as a subprocess. The helper:
   - Closes all FDs > 2
   - Captures real uid/gid before `unshare()`
   - Calls `unshare(USER | PID | NET | IPC | UTS)` — no `NEWNS` (blocked by seccomp in K8s)
   - Writes uid/gid maps
   - `chroot()` into the sandbox root
   - Sets resource limits (`RLIMIT_AS`, `RLIMIT_NPROC`, `RLIMIT_FSIZE`, `RLIMIT_NOFILE`)
   - Forks, inner child sets `PR_SET_PDEATHSIG`, then `execve()` the command

### Isolation guarantees

- **User namespace** — runs as mapped uid/gid, no real root
- **PID namespace** — process isolation
- **Network namespace** — no network (no opt-in yet)
- **IPC namespace** — isolated shared memory / semaphores
- **UTS namespace** — isolated hostname
- **chroot** — filesystem isolation (no mount namespace)
- **Resource limits** — same rlimits as nsjail
- **FD sanitization** — no inherited file descriptors

### Limitations (compared to nsjail)

- No mount namespace (seccomp blocks mount syscall)
- No per-command tmpfs for `/tmp` (cleaned between commands instead)
- No seccomp-bpf per-sandbox
- No cgroup resource limits
- No `/dev` device nodes (no `mknod` in user namespace)
- No network opt-in (always isolated)

---

## Adding a new runner

1. Create a new module in `src/agentjail/sandbox/` (e.g. `firecracker.py`)
2. Implement a class with:
   - `setup_sandbox(root_dir: Path)` — prepare the sandbox filesystem
   - `run_command(sandbox: SandboxState, command: str, timeout: int, env: dict, cwd: str) -> ExecResult` — execute a command
3. Register the runner in `src/agentjail/sandbox/manager.py`
4. Add the runner name to the `Literal` type in `src/agentjail/config.py`
