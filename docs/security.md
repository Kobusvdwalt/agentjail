# Security Audit (May 2026)

## What's solid

- Path traversal protection in filesystem API uses `.resolve()` + `is_relative_to()`
- UUID-generated sandbox IDs prevent path injection in directory creation
- Namespace isolation is comprehensive (PID, NET, MNT, UTS, IPC, USER)
- Read-only system mounts prevent host binary tampering
- `/dev` as tmpfs with only safe device nodes
- `/tmp` as ephemeral tmpfs per command (nsjail) or cleaned between commands (chroot)
- Resource limits set (rlimit_as, rlimit_nproc, rlimit_fsize, rlimit_nofile, max_cpus, time_limit)
- Atomic state file writes with file locking
- User runs as uid 1000 inside jail, capabilities dropped (`keep_caps: false`)
- Chroot runner: FD sanitization closes all inherited file descriptors

## Known vulnerabilities (being addressed)

| ID | Severity | Issue | Plan |
|---|---|---|---|
| SA-01 | CRITICAL | Production Dockerfile runs as root in privileged container | Plan 02 |
| SA-02 | CRITICAL | Host `/proc` bind-mounted into sandboxes — leaks env vars, process info (nsjail only) | Plan 03 |
| SA-03 | CRITICAL | No authentication on API | Future |
| SA-04 | HIGH | Network-enabled sandboxes can reach localhost:8000 (the API itself) and cloud metadata endpoints | Future |
| SA-05 | HIGH | No seccomp-bpf syscall whitelist in nsjail | Future |
| SA-06 | HIGH | No upper bounds on resource limits — API callers can set time_limit=999999 | Plan 04 |
| SA-07 | MEDIUM | TOCTOU race in filesystem API (symlink swap between resolve and operation) | Future |
| SA-08 | MEDIUM | `GET /api/v1/state` exposes internal host paths | Plan 06 |
| SA-09 | MEDIUM | No sandbox count or disk usage limits | Plan 05 |
| SA-10 | LOW | Sandbox IDs are UUID4 (122-bit entropy) — upgrade to 256-bit | Plan 01 |
| SA-11 | LOW | `/sys/fs/cgroup` bind-mounted read-only, exposes cgroup topology (nsjail only) | Plan 03 |

## Runner-specific security notes

### nsjail
- Strongest isolation (mount namespace, seccomp-bpf, cgroup limits)
- Requires elevated container privileges (`CAP_SYS_ADMIN`, apparmor/seccomp disabled)
- `/proc` leak is the biggest concern

### chroot
- No elevated container privileges needed — smaller attack surface at container level
- No mount namespace — chroot escape is theoretically possible with a kernel bug
- No `/proc` or `/sys` exposure — avoids SA-02 and SA-11 entirely
- No network opt-in — all sandboxes are network-isolated (avoids SA-04)

## Most likely sandbox escape vector

A network-enabled sandbox (nsjail with `network: true`) calling `localhost:8000` to manipulate the agentjail API itself (create more sandboxes, read state file with host paths, etc.), combined with `/proc` information to discover secrets. The namespace isolation itself is solid — escape requires a kernel vulnerability.
