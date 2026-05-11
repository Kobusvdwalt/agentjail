"""Chroot sandbox executor.

Invoked as a subprocess by ChrootRunner. Reads a JSON config from stdin,
sets up namespace isolation + chroot, then execs the target command.

Isolation provided:
- User namespace (uid/gid mapping)
- PID namespace
- Network namespace (unless network=true)
- IPC namespace
- UTS namespace
- chroot filesystem isolation
- Resource limits (AS, NPROC, FSIZE, NOFILE)
- FD sanitization (close all FDs > 2)

Does NOT provide (compared to nsjail):
- Mount namespace (blocked by Kubernetes seccomp baseline)
- tmpfs mounts (requires mount syscall)
- seccomp-bpf filtering
- cgroup resource limits
"""

import ctypes
import json
import os
import resource
import signal
import sys


def main() -> None:
    config = json.loads(sys.stdin.buffer.read())

    root_dir = config["root_dir"]
    uid = config.get("uid", 1000)
    gid = config.get("gid", 1000)
    cwd = config.get("cwd", "/home")
    env = config.get("env", {})
    command = config["command"]
    network = config.get("network", False)
    rlimit_as = config.get("rlimit_as", 256 * 1024 * 1024)
    rlimit_nproc = config.get("rlimit_nproc", 64)
    rlimit_fsize = config.get("rlimit_fsize", 50 * 1024 * 1024)
    rlimit_nofile = config.get("rlimit_nofile", 256)

    # --- FD sanitization ---
    # Defense in depth: close all FDs > 2.
    # Python subprocess already does this with close_fds=True, but we
    # do it again to catch any leaks.
    try:
        max_fd = os.sysconf("SC_OPEN_MAX")
    except ValueError, OSError:
        max_fd = 4096
    os.closerange(3, max_fd)

    # --- Namespace creation ---
    libc = ctypes.CDLL("libc.so.6", use_errno=True)

    # Capture real uid/gid BEFORE unshare — after CLONE_NEWUSER,
    # getuid() returns 65534 (nobody) until we write uid_map.
    real_uid = os.getuid()
    real_gid = os.getgid()

    CLONE_NEWUSER = 0x10000000
    CLONE_NEWPID = 0x20000000
    CLONE_NEWNET = 0x40000000
    CLONE_NEWIPC = 0x08000000
    CLONE_NEWUTS = 0x04000000

    flags = CLONE_NEWUSER | CLONE_NEWPID | CLONE_NEWIPC | CLONE_NEWUTS
    if not network:
        flags |= CLONE_NEWNET

    ret = libc.unshare(flags)
    if ret != 0:
        errno = ctypes.get_errno()
        print(f"chroot-exec: unshare failed: {os.strerror(errno)}", file=sys.stderr)
        sys.exit(1)

    # --- UID/GID mapping ---
    # Must happen after unshare(NEWUSER) and before chroot.
    # After this, we have CAP_SYS_CHROOT in the new user namespace.

    with open("/proc/self/setgroups", "w") as f:
        f.write("deny")
    with open("/proc/self/uid_map", "w") as f:
        f.write(f"{uid} {real_uid} 1\n")
    with open("/proc/self/gid_map", "w") as f:
        f.write(f"{gid} {real_gid} 1\n")

    # --- Chroot ---
    os.chroot(root_dir)
    os.chdir(cwd)

    # --- Resource limits ---
    resource.setrlimit(resource.RLIMIT_AS, (rlimit_as, rlimit_as))
    resource.setrlimit(resource.RLIMIT_NPROC, (rlimit_nproc, rlimit_nproc))
    resource.setrlimit(resource.RLIMIT_FSIZE, (rlimit_fsize, rlimit_fsize))
    resource.setrlimit(resource.RLIMIT_NOFILE, (rlimit_nofile, rlimit_nofile))

    # --- Environment ---
    os.environ.clear()
    for key, val in env.items():
        os.environ[key] = val

    # --- Fork for PID namespace ---
    # unshare(NEWPID) only takes effect for children, not the calling process.
    # The child becomes PID 1 in the new PID namespace.
    pid = os.fork()
    if pid == 0:
        # Inner child — PID 1 in the new PID namespace.
        # Auto-kill if parent dies (belt-and-suspenders with process group kill).
        PR_SET_PDEATHSIG = 1
        libc.prctl(PR_SET_PDEATHSIG, signal.SIGKILL, 0, 0, 0)

        try:
            os.execvpe(command[0], command, dict(os.environ))
        except OSError as e:
            print(f"chroot-exec: exec failed: {e}", file=sys.stderr)
            os._exit(127)
    else:
        # Outer process: wait for inner child.
        _, status = os.waitpid(pid, 0)
        if os.WIFEXITED(status):
            sys.exit(os.WEXITSTATUS(status))
        elif os.WIFSIGNALED(status):
            sys.exit(128 + os.WTERMSIG(status))
        sys.exit(1)


if __name__ == "__main__":
    main()
