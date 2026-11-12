from pathlib import Path
from math import ceil

from agentjail.config import AgentjailSettings
from agentjail.sandbox import egress
from agentjail.sandbox.models import ExecResult, SandboxState
from agentjail.sandbox.process import run_process
from agentjail.sandbox.resources import mount_roots


EGRESS_BIN = "/.agentjail/egress"
EGRESS_SOCKET = "/.agentjail/egress.sock"


class NsjailRunner:
    def __init__(self, settings: AgentjailSettings) -> None:
        self.settings = settings
        self.egress_policy = (
            egress.EgressPolicy.from_patterns(
                settings.network_allow, settings.network_allow_private
            )
            if settings.network_allow
            else None
        )
        if self.egress_policy and not Path(settings.egress_bin).is_file():
            raise ValueError(
                f"AGENTJAIL_NETWORK_ALLOW needs the egress forwarder at {settings.egress_bin}"
            )

    def setup_sandbox(self, root_dir: Path) -> None:
        """Create directories that nsjail will bind-mount."""
        (root_dir / "home").mkdir(exist_ok=True)
        (root_dir / "uploads").mkdir(exist_ok=True)

    async def run_command(
        self,
        sandbox: SandboxState,
        command: list[str],
        timeout: int | None = None,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> ExecResult:
        effective_timeout = timeout or sandbox.config.time_limit
        if sandbox.config.network or not self.egress_policy:
            args = self._build_args(sandbox, command, ceil(effective_timeout), env, cwd)
            return await self._run(args, effective_timeout)

        async with egress.serve(
            self.egress_policy, self.settings.egress_socket_dir
        ) as socket_path:
            args = self._build_args(
                sandbox, command, ceil(effective_timeout), env, cwd, socket_path
            )
            return await self._run(args, effective_timeout)

    async def _run(self, args: list[str], timeout: float) -> ExecResult:
        result = await run_process(
            args,
            timeout=timeout,
            output_limit=self.settings.max_output_bytes,
        )
        result.timed_out = result.timed_out or result.exit_code in (-9, 137)
        return result

    def _build_args(
        self,
        sandbox: SandboxState,
        command: list[str],
        timeout: int,
        env: dict[str, str] | None,
        cwd: str | None,
        egress_socket: Path | None = None,
    ) -> list[str]:
        args = [
            self.settings.nsjail_bin,
            "--mode",
            "o",
            "--time_limit",
            str(timeout),
            "--rlimit_as",
            str(sandbox.config.memory_limit),
            "--max_cpus",
            "1",
            "--rlimit_nproc",
            str(sandbox.config.pids_limit),
            "--rlimit_fsize",
            "50",
            "--rlimit_nofile",
            "256",
            "--user",
            "1000",
            "--group",
            "1000",
        ]

        for ro_mount in self.settings.bind_mount_ro:
            if Path(ro_mount).exists():
                args.extend(["--bindmount_ro", ro_mount])

        args.extend(["--bindmount", f"{sandbox.root_dir}/home:/home"])
        args.extend(["--bindmount_ro", f"{sandbox.root_dir}/uploads:/uploads"])

        args.extend(self._resource_mounts(sandbox))

        args.append("--disable_proc")
        args.extend(["--mount", "none:/tmp:tmpfs:size=67108864"])
        args.extend(["--mount", "none:/dev:tmpfs"])
        for dev in ("/dev/null", "/dev/zero", "/dev/urandom", "/dev/random"):
            if Path(dev).exists():
                args.extend(["--bindmount_ro", dev])

        if egress_socket:
            args.extend(["--bindmount_ro", f"{self.settings.egress_bin}:{EGRESS_BIN}"])
            args.extend(["--bindmount_ro", f"{egress_socket}:{EGRESS_SOCKET}"])

        args.extend(["--cwd", cwd or sandbox.config.cwd])

        merged_env = {
            "PATH": "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": "/home",
            "TERM": "xterm",
        }
        if egress_socket:
            proxy = f"http://127.0.0.1:{self.settings.egress_port}"
            for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
                merged_env[name] = proxy
            merged_env["NO_PROXY"] = merged_env["no_proxy"] = "localhost,127.0.0.1,::1"
        merged_env.update(sandbox.config.env)
        if env:
            merged_env.update(env)
        for key, val in merged_env.items():
            args.extend(["--env", f"{key}={val}"])

        if sandbox.config.network:
            args.append("--disable_clone_newnet")

        log_file = str(Path(sandbox.root_dir) / "nsjail.log")
        args.extend(["--log", log_file])
        args.append("--")
        if egress_socket:
            args.extend(
                [EGRESS_BIN, str(self.settings.egress_port), EGRESS_SOCKET, "--"]
            )
        args.extend(command)
        return args

    def _resource_mounts(self, sandbox: SandboxState) -> list[str]:
        """Read-only mounts for the shared resources this sandbox may see.

        The whole directory when the sandbox asked for everything, which is both
        the default and the cheap path — one mount instead of a walk of the
        tree. Otherwise the selection is collapsed to its shallowest covering
        paths and each is mounted at its place under `/resources`.

        This is where the patterns are actually enforced. What is not mounted
        does not exist inside the jail, so an agent cannot read it whether or
        not the listing mentioned it.
        """
        resources_dir = self.settings.resources_dir

        if not resources_dir or not resources_dir.is_dir():
            return []

        patterns = sandbox.config.resources

        if not patterns:
            return []

        if any(pattern in ("*", "**") for pattern in patterns):
            return ["--bindmount_ro", f"{resources_dir}:/resources"]

        args: list[str] = []

        for rel in mount_roots(resources_dir, patterns):
            args.extend(
                ["--bindmount_ro", f"{resources_dir / rel}:/resources/{rel.as_posix()}"]
            )

        return args
