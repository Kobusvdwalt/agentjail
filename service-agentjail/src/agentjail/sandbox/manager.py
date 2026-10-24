import asyncio
import shutil
from datetime import datetime, timezone
from pathlib import Path
import secrets

import yaml

from agentjail.sandbox.filesystem import _resolve_safe
from agentjail.sandbox.lease import ExecutionLease, LeaseConflict, LeaseGrant

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
from agentjail.sandbox.resources import ALL_RESOURCES, selected_paths
from agentjail.sandbox.bare import BareRunner
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


class SandboxCapacityExceeded(Exception):
    pass


class SandboxManager:
    def __init__(self, settings: AgentjailSettings) -> None:
        self.settings = settings
        self._active: dict[str, set[asyncio.Task[ExecResult]]] = {}
        self._leases: dict[str, ExecutionLease] = {}
        self._workspace_locks: dict[str, asyncio.Lock] = {}
        self._closing = False
        self.state = StateManager(settings.state_file)
        self.runner: NsjailRunner | ChrootRunner | BareRunner
        if settings.runner == "bare":
            self.runner = BareRunner(settings)
        elif settings.runner == "chroot":
            self.runner = ChrootRunner(settings)
        else:
            self.runner = NsjailRunner(settings)
        settings.sandbox_base_dir.mkdir(parents=True, exist_ok=True)

    def _validate_limits(
        self,
        time_limit: int | None,
        memory_limit: int | None,
        pids_limit: int | None,
    ) -> tuple[int, int, int]:
        if any(
            value is not None and value <= 0
            for value in (time_limit, memory_limit, pids_limit)
        ):
            raise ValueError("Resource limits must be positive")
        tl = min(
            time_limit or self.settings.default_time_limit, self.settings.max_time_limit
        )
        ml = min(
            memory_limit or self.settings.default_memory_limit,
            self.settings.max_memory_limit,
        )
        pl = min(
            pids_limit or self.settings.default_pids_limit, self.settings.max_pids_limit
        )
        return tl, ml, pl

    async def sandbox_run(
        self,
        command: str,
        time_limit: int | None = None,
        memory_limit: int | None = None,
        env: dict[str, str] | None = None,
    ) -> tuple[ExecResult, str]:
        sandbox_id = secrets.token_urlsafe(32)
        root_dir = self.settings.sandbox_base_dir / sandbox_id
        root_dir.mkdir()
        self.runner.setup_sandbox(root_dir)

        tl, ml, pl = self._validate_limits(time_limit, memory_limit, None)
        config = SandboxConfig(
            time_limit=tl,
            memory_limit=ml,
            pids_limit=pl,
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
        resources: list[str] | None = None,
    ) -> SandboxState:
        sandbox_id = secrets.token_urlsafe(32)
        root_dir = self.settings.sandbox_base_dir / sandbox_id
        root_dir.mkdir()
        self.runner.setup_sandbox(root_dir)

        now = datetime.now(timezone.utc)
        tl, ml, pl = self._validate_limits(time_limit, memory_limit, pids_limit)
        config = SandboxConfig(
            name=name,
            time_limit=tl,
            memory_limit=ml,
            pids_limit=pl,
            env=env or {},
            cwd=cwd,
            network=network,
            # `None` means the caller expressed no opinion and gets everything;
            # an explicit `[]` means they asked for nothing and get nothing.
            resources=list(ALL_RESOURCES) if resources is None else list(resources),
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
        async with self._workspace_locks.setdefault(sandbox_id, asyncio.Lock()):
            with self.state.transaction() as state:
                sandbox = state.sandboxes.get(sandbox_id)
                if not sandbox:
                    raise SandboxNotFound(sandbox_id)
                sandbox.status = "stopped"
                sandbox.updated_at = datetime.now(timezone.utc)
            await self._revoke_lease(sandbox_id)
            return sandbox

    async def sandbox_remove(self, sandbox_id: str, force: bool = False) -> None:
        async with self._workspace_locks.setdefault(sandbox_id, asyncio.Lock()):
            with self.state.transaction() as state:
                sandbox = state.sandboxes.get(sandbox_id)
                if not sandbox:
                    raise SandboxNotFound(sandbox_id)
                if sandbox.status == "running" and not force:
                    raise SandboxStillRunning(sandbox_id)
                state.sandboxes.pop(sandbox_id)
            await self._revoke_lease(sandbox_id)
            shutil.rmtree(sandbox.root_dir, ignore_errors=True)

    async def acquire_lease(self, sandbox_id: str, seconds: int) -> LeaseGrant:
        if not 1 <= seconds <= 300:
            raise ValueError("Lease duration must be between 1 and 300 seconds")
        async with self._workspace_locks.setdefault(sandbox_id, asyncio.Lock()):
            self._get_sandbox(sandbox_id)
            if self._closing:
                raise SandboxNotRunning(sandbox_id)
            current = self._leases.get(sandbox_id)
            if current and current.deadline > asyncio.get_running_loop().time():
                raise LeaseConflict("Workspace already has an active lease")
            await self._revoke_lease(sandbox_id)
            with self.state.transaction() as state:
                sandbox = state.sandboxes[sandbox_id]
                sandbox.status = "running"
                sandbox.updated_at = datetime.now(timezone.utc)
            lease = ExecutionLease(
                secrets.token_urlsafe(32), asyncio.get_running_loop().time() + seconds
            )
            self._leases[sandbox_id] = lease
            lease.timer = asyncio.create_task(self._expire_lease(sandbox_id, lease))
            return LeaseGrant(lease_token=lease.token, lease_seconds=seconds)

    async def renew_lease(
        self, sandbox_id: str, token: str, seconds: int
    ) -> LeaseGrant:
        if not 1 <= seconds <= 300:
            raise ValueError("Lease duration must be between 1 and 300 seconds")
        async with self._workspace_locks.setdefault(sandbox_id, asyncio.Lock()):
            self._get_sandbox(sandbox_id, require_running=True)
            lease = self._require_lease(sandbox_id, token)
            lease.timer.cancel()
            lease.deadline = asyncio.get_running_loop().time() + seconds
            lease.timer = asyncio.create_task(self._expire_lease(sandbox_id, lease))
            return LeaseGrant(lease_token=lease.token, lease_seconds=seconds)

    def _require_lease(self, sandbox_id: str, token: str) -> ExecutionLease:
        lease = self._leases.get(sandbox_id)
        if (
            not lease
            or not secrets.compare_digest(token.encode(), lease.token.encode())
            or lease.deadline <= asyncio.get_running_loop().time()
        ):
            raise LeaseConflict("Execution lease is missing, expired or revoked")
        return lease

    async def _expire_lease(self, sandbox_id: str, lease: ExecutionLease) -> None:
        await asyncio.sleep(max(0, lease.deadline - asyncio.get_running_loop().time()))
        async with self._workspace_locks.setdefault(sandbox_id, asyncio.Lock()):
            if self._leases.get(sandbox_id) is not lease:
                return
            with self.state.transaction() as state:
                sandbox = state.sandboxes.get(sandbox_id)
                if sandbox:
                    sandbox.status = "stopped"
                    sandbox.updated_at = datetime.now(timezone.utc)
            await self._revoke_lease(sandbox_id)

    async def _revoke_lease(self, sandbox_id: str) -> None:
        lease = self._leases.pop(sandbox_id, None)
        if lease and lease.timer is not asyncio.current_task():
            lease.timer.cancel()
        await self._cancel_commands(sandbox_id)

    async def sandbox_shell(
        self,
        sandbox_id: str,
        command: str,
        timeout: int | None = None,
        lease_token: str = "",
    ) -> ExecResult:
        sandbox = self._get_sandbox(sandbox_id, require_running=True)
        if self._closing:
            raise SandboxNotRunning(sandbox_id)
        lease = self._require_lease(sandbox_id, lease_token)
        if sum(map(len, self._active.values())) >= self.settings.max_active_commands:
            raise SandboxCapacityExceeded()
        if timeout is not None and timeout <= 0:
            raise ValueError("Command timeout must be positive")
        effective_timeout = min(
            timeout or sandbox.config.time_limit,
            self.settings.max_time_limit,
            lease.deadline - asyncio.get_running_loop().time(),
        )
        task = asyncio.create_task(
            self.runner.run_command(
                sandbox, ["/bin/sh", "-c", command], timeout=effective_timeout
            )
        )
        active = self._active.setdefault(sandbox_id, set())
        active.add(task)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            if asyncio.current_task().cancelling():
                if not task.cancelling():
                    task.cancel()
                await asyncio.shield(asyncio.gather(task, return_exceptions=True))
                raise
            return ExecResult(exit_code=-1, stdout="", stderr="", killed=True)
        finally:
            active.discard(task)
            if not active:
                self._active.pop(sandbox_id, None)

    async def _cancel_commands(self, sandbox_id: str) -> None:
        tasks = list(self._active.get(sandbox_id, ()))
        for task in tasks:
            if not task.cancelling():
                task.cancel()
        await asyncio.shield(asyncio.gather(*tasks, return_exceptions=True))

    async def shutdown(self) -> None:
        self._closing = True
        timers = [lease.timer for lease in self._leases.values()]
        self._leases.clear()
        for timer in timers:
            timer.cancel()
        await asyncio.gather(*timers, return_exceptions=True)
        await asyncio.gather(*(self._cancel_commands(id) for id in list(self._active)))

    async def sandbox_host_file(self, sandbox_id: str, path: str) -> dict:
        sandbox = self._get_sandbox(sandbox_id)
        root_dir = Path(sandbox.root_dir)
        source = fs_resolve(root_dir, path)
        hosted_dir = root_dir / "hosted"
        hosted_dir.mkdir(exist_ok=True)
        ext = source.suffix
        dest_name = f"{secrets.token_urlsafe(16)}{ext}"
        dest = hosted_dir / dest_name
        shutil.copy2(source, dest)
        from urllib.parse import quote

        return {
            "download_url": f"/api/v1/sandbox/{sandbox_id}/hosted/{dest_name}?filename={quote(source.name)}",
            "filename": source.name,
            "size": dest.stat().st_size,
        }

    async def sandbox_hosted_resolve(self, sandbox_id: str, filename: str) -> Path:
        sandbox = self._get_sandbox(sandbox_id)
        root_dir = Path(sandbox.root_dir)
        hosted_dir = root_dir / "hosted"
        resolved = _resolve_safe(hosted_dir, filename)
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

    async def sandbox_read_media(self, sandbox_id: str, path: str) -> tuple[bytes, str]:
        """Read a media file from the sandbox and return its raw bytes and MIME type."""
        import mimetypes

        sandbox = self._get_sandbox(sandbox_id)
        resolved = fs_resolve(Path(sandbox.root_dir), path)
        mime_type, _ = mimetypes.guess_type(resolved.name)
        if mime_type is None:
            raise ValueError(f"Cannot determine MIME type for: {path}")
        if not (mime_type.startswith("image/") or mime_type.startswith("audio/")):
            raise ValueError(
                f"Unsupported media type '{mime_type}' for: {path}. "
                "Only image/* and audio/* are supported."
            )
        return resolved.read_bytes(), mime_type

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

    def list_resources(self, max_depth: int = 2, sandbox_id: str | None = None) -> dict:
        """List files in the resources directory and parse any SKILL.md files.

        Scoped to what the sandbox can actually reach. `sandbox_id` is optional
        only so callers with no sandbox in hand still work; passing one is what
        makes the listing agree with the mount, and a listing that promises
        files the sandbox cannot open is worse than no listing at all.
        """
        resources_dir = self.settings.resources_dir
        if not resources_dir or not resources_dir.is_dir():
            return {"available": False, "files": [], "skills": []}

        patterns = list(ALL_RESOURCES)
        if sandbox_id is not None:
            patterns = self._get_sandbox(sandbox_id).config.resources

        files: list[str] = []
        skills: list[dict[str, str]] = []

        base = resources_dir

        for rel in selected_paths(base, patterns):
            item = base / rel

            # Enforce max depth
            if len(rel.parts) > max_depth:
                continue

            entry = rel.as_posix()
            if item.is_dir():
                entry += "/"
            files.append(entry)

            if item.is_file() and item.name == "SKILL.md":
                skill = _parse_skill_frontmatter(item)
                if skill:
                    skill["location"] = f"/resources/{rel.as_posix()}"
                    skills.append(skill)

        return {"available": True, "files": files, "skills": skills}


def _parse_skill_frontmatter(path: Path) -> dict[str, str] | None:
    """Parse YAML frontmatter from a SKILL.md file, returning name and description."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    if not text.startswith("---"):
        return None

    end = text.find("---", 3)
    if end == -1:
        return None

    try:
        front = yaml.safe_load(text[3:end])
    except yaml.YAMLError:
        return None

    if not isinstance(front, dict):
        return None

    name = front.get("name")
    description = front.get("description")
    if not name or not description:
        return None

    return {"name": str(name), "description": str(description)}
