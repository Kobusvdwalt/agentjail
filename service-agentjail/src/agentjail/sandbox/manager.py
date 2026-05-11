import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from agentjail.sandbox.filesystem import _resolve_safe

from agentjail.config import AgentjailSettings
from agentjail.sandbox.filesystem import (
    fs_resolve,
    fs_write,
)
from agentjail.sandbox.models import (
    ExecResult,
    SandboxConfig,
    SandboxState,
)
from agentjail.sandbox.chroot import ChrootRunner
from agentjail.sandbox.nsjail import NsjailRunner
from agentjail.state import StateManager


class SandboxNotFound(Exception):
    pass


class SandboxNotRunning(Exception):
    pass


class SandboxAlreadyExists(Exception):
    pass


class SandboxStillRunning(Exception):
    pass


class SandboxManager:
    def __init__(self, settings: AgentjailSettings) -> None:
        self.settings = settings
        self.state = StateManager(settings.state_file)
        self.runner: NsjailRunner | ChrootRunner = (
            ChrootRunner(settings)
            if settings.runner == "chroot"
            else NsjailRunner(settings)
        )
        settings.sandbox_base_dir.mkdir(parents=True, exist_ok=True)

    async def sandbox_run(
        self,
        command: str,
        time_limit: int | None = None,
        memory_limit: int | None = None,
        env: dict[str, str] | None = None,
    ) -> tuple[ExecResult, str]:
        sandbox_id = str(uuid4())
        root_dir = self.settings.sandbox_base_dir / sandbox_id
        root_dir.mkdir()
        self.runner.setup_sandbox(root_dir)

        config = SandboxConfig(
            time_limit=time_limit or self.settings.default_time_limit,
            memory_limit=memory_limit or self.settings.default_memory_limit,
            pids_limit=self.settings.default_pids_limit,
            env=env or {},
        )
        sandbox = SandboxState(
            id=sandbox_id,
            status="running",
            config=config,
            root_dir=str(root_dir),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        try:
            result = await self.runner.run_command(
                sandbox, ["/bin/sh", "-c", command], timeout=config.time_limit
            )
            return result, sandbox_id
        finally:
            shutil.rmtree(root_dir, ignore_errors=True)

    async def sandbox_create(
        self,
        name: str | None = None,
        time_limit: int | None = None,
        memory_limit: int | None = None,
        pids_limit: int | None = None,
        env: dict[str, str] | None = None,
        cwd: str = "/home",
        network: bool = False,
    ) -> SandboxState:
        sandbox_id = str(uuid4())
        root_dir = self.settings.sandbox_base_dir / sandbox_id
        root_dir.mkdir()
        self.runner.setup_sandbox(root_dir)

        now = datetime.now(timezone.utc)
        config = SandboxConfig(
            name=name,
            time_limit=time_limit or self.settings.default_time_limit,
            memory_limit=memory_limit or self.settings.default_memory_limit,
            pids_limit=pids_limit or self.settings.default_pids_limit,
            env=env or {},
            cwd=cwd,
            network=network,
        )
        sandbox = SandboxState(
            id=sandbox_id,
            name=name,
            status="running",
            config=config,
            root_dir=str(root_dir),
            created_at=now,
            updated_at=now,
        )

        with self.state.transaction() as state:
            state.sandboxes[sandbox_id] = sandbox

        return sandbox

    async def sandbox_list(self) -> list[SandboxState]:
        return list(self.state.read().sandboxes.values())

    async def sandbox_inspect(self, sandbox_id: str) -> SandboxState:
        return self._get_sandbox(sandbox_id)

    async def sandbox_stop(self, sandbox_id: str) -> SandboxState:
        with self.state.transaction() as state:
            sandbox = state.sandboxes.get(sandbox_id)
            if not sandbox:
                raise SandboxNotFound(sandbox_id)
            sandbox.status = "stopped"
            sandbox.updated_at = datetime.now(timezone.utc)
        return sandbox

    async def sandbox_remove(self, sandbox_id: str, force: bool = False) -> None:
        with self.state.transaction() as state:
            sandbox = state.sandboxes.get(sandbox_id)
            if not sandbox:
                raise SandboxNotFound(sandbox_id)
            if sandbox.status == "running" and not force:
                raise SandboxStillRunning(sandbox_id)
            state.sandboxes.pop(sandbox_id)
        shutil.rmtree(sandbox.root_dir, ignore_errors=True)

    async def sandbox_shell(
        self,
        sandbox_id: str,
        command: str,
        timeout: int | None = None,
    ) -> ExecResult:
        sandbox = self._get_sandbox(sandbox_id, require_running=True)
        return await self.runner.run_command(
            sandbox, ["/bin/sh", "-c", command], timeout=timeout
        )

    async def sandbox_download(self, sandbox_id: str, path: str) -> dict:
        sandbox = self._get_sandbox(sandbox_id)
        root_dir = Path(sandbox.root_dir)
        source = fs_resolve(root_dir, path)
        downloads_dir = root_dir / "downloads"
        downloads_dir.mkdir(exist_ok=True)
        ext = source.suffix
        dest_name = f"{uuid4()}{ext}"
        dest = downloads_dir / dest_name
        shutil.copy2(source, dest)
        return {
            "download_url": f"/api/v1/sandbox/{sandbox_id}/downloads/{dest_name}",
            "filename": source.name,
            "size": dest.stat().st_size,
        }

    async def sandbox_download_resolve(self, sandbox_id: str, filename: str) -> Path:
        sandbox = self._get_sandbox(sandbox_id)
        root_dir = Path(sandbox.root_dir)
        downloads_dir = root_dir / "downloads"
        resolved = _resolve_safe(downloads_dir, filename)
        if not resolved.is_file():
            raise FileNotFoundError(f"Not a file: {filename}")
        return resolved

    async def sandbox_fs_download(self, sandbox_id: str, path: str) -> Path:
        sandbox = self._get_sandbox(sandbox_id)
        return fs_resolve(Path(sandbox.root_dir), path)

    async def sandbox_fs_write(
        self, sandbox_id: str, path: str, content: str | bytes
    ) -> None:
        sandbox = self._get_sandbox(sandbox_id)
        fs_write(Path(sandbox.root_dir), path, content)

    def _get_sandbox(
        self, sandbox_id: str, require_running: bool = False
    ) -> SandboxState:
        state = self.state.read()
        sandbox = state.sandboxes.get(sandbox_id)
        if not sandbox:
            raise SandboxNotFound(sandbox_id)
        if require_running and sandbox.status != "running":
            raise SandboxNotRunning(sandbox_id)
        return sandbox
