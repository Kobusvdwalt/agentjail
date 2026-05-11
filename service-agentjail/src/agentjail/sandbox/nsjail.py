import asyncio
from pathlib import Path

from agentjail.config import AgentjailSettings
from agentjail.sandbox.models import ExecResult, SandboxState


class NsjailRunner:
    def __init__(self, settings: AgentjailSettings) -> None:
        self.settings = settings

    def setup_sandbox(self, root_dir: Path) -> None:
        """Create the home directory that nsjail will bind-mount."""
        (root_dir / "home").mkdir(exist_ok=True)

    async def run_command(
        self,
        sandbox: SandboxState,
        command: list[str],
        timeout: int | None = None,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> ExecResult:
        effective_timeout = timeout or sandbox.config.time_limit
        args = self._build_args(sandbox, command, effective_timeout, env, cwd)

        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=effective_timeout + 5,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return ExecResult(exit_code=-1, stdout="", stderr="", timed_out=True)

        return ExecResult(
            exit_code=proc.returncode or 0,
            stdout=stdout.decode(errors="replace"),
            stderr=stderr.decode(errors="replace"),
        )

    def _build_args(
        self,
        sandbox: SandboxState,
        command: list[str],
        timeout: int,
        env: dict[str, str] | None,
        cwd: str | None,
    ) -> list[str]:
        args = [
            self.settings.nsjail_bin,
            "--mode", "o",
            "--time_limit", str(timeout),
            "--rlimit_as", str(sandbox.config.memory_limit),
            "--max_cpus", "1",
            "--rlimit_nproc", str(sandbox.config.pids_limit),
            "--rlimit_fsize", "50",
            "--rlimit_nofile", "256",
            "--user", "1000",
            "--group", "1000",
        ]

        for ro_mount in self.settings.bind_mount_ro:
            if Path(ro_mount).exists():
                args.extend(["--bindmount_ro", ro_mount])

        args.extend(["--bindmount", f"{sandbox.root_dir}/home:/home"])

        args.extend(["--mount", "none:/tmp:tmpfs:size=67108864"])
        args.append("--disable_proc")
        args.extend(["--bindmount_ro", "/proc"])
        args.extend(["--mount", "none:/dev:tmpfs"])
        for dev in ("/dev/null", "/dev/zero", "/dev/urandom", "/dev/random"):
            if Path(dev).exists():
                args.extend(["--bindmount_ro", dev])

        args.extend(["--cwd", cwd or sandbox.config.cwd])

        merged_env = {"PATH": "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin", "HOME": "/home", "TERM": "xterm"}
        merged_env.update(sandbox.config.env)
        if env:
            merged_env.update(env)
        for key, val in merged_env.items():
            args.extend(["--env", f"{key}={val}"])

        if sandbox.config.network:
            args.append("--disable_clone_newnet")

        args.extend(["--log_fd", "2"])
        args.append("--")
        args.extend(command)
        return args
