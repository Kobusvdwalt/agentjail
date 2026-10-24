"""Bare sandbox runner — NO isolation whatsoever.

⚠️  WARNING: This runner provides ZERO security isolation. Commands run
directly on the host as the service process user. It exists solely for
deployment in environments where nsjail/chroot are not available (e.g.
strictly managed Kubernetes clusters that deny all capabilities).

Use this runner ONLY for prototyping, development, or trusted workloads.

Provides:
- A per-sandbox working directory
- Command timeouts (via asyncio)
- The full MCP tool surface

Does NOT provide:
- Filesystem isolation (commands see the entire host filesystem)
- User namespace / UID separation
- PID / network / IPC namespace isolation
- cgroup resource limits
- Any form of privilege reduction
"""

from pathlib import Path

from agentjail.config import AgentjailSettings
from agentjail.sandbox.models import ExecResult, SandboxState
from agentjail.sandbox.process import run_process


class BareRunner:
    def __init__(self, settings: AgentjailSettings) -> None:
        self.settings = settings

    def setup_sandbox(self, root_dir: Path) -> None:
        """Create workspace directories — no isolation setup needed."""
        (root_dir / "home").mkdir(exist_ok=True)
        (root_dir / "tmp").mkdir(exist_ok=True)

    async def run_command(
        self,
        sandbox: SandboxState,
        command: list[str],
        timeout: int | None = None,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> ExecResult:
        effective_timeout = timeout or sandbox.config.time_limit
        root_dir = Path(sandbox.root_dir)

        # Working directory is relative to the sandbox root_dir.
        work_cwd = cwd or sandbox.config.cwd
        # Map the "virtual" cwd to the real path inside the sandbox dir.
        # e.g. /home -> <root_dir>/home
        if work_cwd.startswith("/"):
            work_cwd = work_cwd.lstrip("/")
        real_cwd = root_dir / work_cwd
        real_cwd.mkdir(parents=True, exist_ok=True)

        # Build environment.
        merged_env = {
            "PATH": "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": str(root_dir / "home"),
            "TERM": "xterm",
            "TMPDIR": str(root_dir / "tmp"),
        }
        merged_env.update(sandbox.config.env)
        if env:
            merged_env.update(env)

        return await run_process(
            command,
            timeout=effective_timeout,
            output_limit=self.settings.max_output_bytes,
            cwd=str(real_cwd),
            env=merged_env,
        )
