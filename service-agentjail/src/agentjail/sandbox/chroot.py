"""Chroot-based sandbox runner.

Works without CAP_SYS_ADMIN or custom seccomp profiles. Suitable for
Kubernetes pods running under the 'baseline' PodSecurity profile.

Provides: user, PID, network, IPC, UTS namespace isolation + chroot
filesystem isolation + resource limits + FD sanitization.

Does NOT provide (compared to nsjail):
- Mount namespace (seccomp blocks the mount syscall)
- Per-command tmpfs for /tmp (cleaned between commands instead)
- seccomp-bpf per-sandbox
- cgroup resource limits
- /dev device nodes (no mknod in user namespace)
"""

import asyncio
import json
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

from agentjail.config import AgentjailSettings
from agentjail.sandbox.models import ExecResult, SandboxState


class ChrootRunner:
    def __init__(self, settings: AgentjailSettings) -> None:
        self.settings = settings

    def setup_sandbox(self, root_dir: Path) -> None:
        """Prepare the chroot directory with hardlinked system files.

        Creates the following layout inside root_dir:
          /usr/       — hardlinked from container (fast, no disk duplication)
          /etc/       — copied from container (cross-device mounts in k8s)
          /bin -> usr/bin    (symlink, matching Ubuntu/Debian layout)
          /sbin -> usr/sbin
          /lib -> usr/lib
          /lib64 -> usr/lib64
          /home/      — writable sandbox workspace
          /tmp/       — writable, cleaned between commands
        """
        (root_dir / "home").mkdir(exist_ok=True)
        (root_dir / "tmp").mkdir(exist_ok=True)

        # Copy /usr — try hardlinks first (fast, no disk duplication on same FS).
        # Falls back to regular copy if hardlinks fail (overlayfs, cross-device).
        usr_dst = root_dir / "usr"
        result = subprocess.run(
            ["cp", "-al", "/usr", str(usr_dst)],
            capture_output=True,
        )
        if result.returncode != 0:
            # Remove partial directory tree from failed hardlink attempt.
            if usr_dst.exists():
                shutil.rmtree(usr_dst, ignore_errors=True)
            subprocess.run(
                ["cp", "-a", "--no-preserve=ownership", "/usr", str(usr_dst)],
                check=True,
                capture_output=True,
            )

        # Copy /etc — k8s configmap mounts cause cross-device hardlink failures,
        # so we always use a regular copy here. Ignore errors from unreadable
        # files (shadow, ssl private keys) — they aren't needed in sandboxes.
        subprocess.run(
            ["cp", "-a", "--no-preserve=ownership", "/etc", str(root_dir / "etc")],
            capture_output=True,
        )

        # Create symlinks matching the Ubuntu/Debian merged-usr layout:
        # /bin -> usr/bin, /sbin -> usr/sbin, /lib -> usr/lib, etc.
        for link_name, target in [
            ("bin", "usr/bin"),
            ("sbin", "usr/sbin"),
            ("lib", "usr/lib"),
            ("lib64", "usr/lib64"),
        ]:
            link_path = root_dir / link_name
            if not link_path.exists() and Path(f"/{link_name}").exists():
                link_path.symlink_to(target)

    async def run_command(
        self,
        sandbox: SandboxState,
        command: list[str],
        timeout: int | None = None,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> ExecResult:
        effective_timeout = timeout or sandbox.config.time_limit

        # Clean /tmp before each command — analogous to nsjail's per-command tmpfs.
        tmp_dir = Path(sandbox.root_dir) / "tmp"
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)
        tmp_dir.mkdir(exist_ok=True)

        # Build merged environment.
        merged_env = {
            "PATH": "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": "/home",
            "TERM": "xterm",
        }
        merged_env.update(sandbox.config.env)
        if env:
            merged_env.update(env)

        # Config blob for the _chroot_exec helper process.
        config = {
            "root_dir": sandbox.root_dir,
            "command": command,
            "cwd": cwd or sandbox.config.cwd,
            "env": merged_env,
            "uid": 1000,
            "gid": 1000,
            "network": sandbox.config.network,
            "rlimit_as": sandbox.config.memory_limit * 1024 * 1024,
            "rlimit_nproc": sandbox.config.pids_limit,
            "rlimit_fsize": 50 * 1024 * 1024,
            "rlimit_nofile": 256,
        }

        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "agentjail.sandbox._chroot_exec",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=json.dumps(config).encode()),
                timeout=effective_timeout,
            )
        except asyncio.TimeoutError:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await proc.wait()
            return ExecResult(exit_code=-1, stdout="", stderr="", timed_out=True)

        return ExecResult(
            exit_code=proc.returncode or 0,
            stdout=stdout.decode(errors="replace"),
            stderr=stderr.decode(errors="replace"),
        )
