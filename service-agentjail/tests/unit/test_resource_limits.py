import httpx

from agentjail.config import AgentjailSettings
from agentjail.sandbox.manager import SandboxManager
from agentjail.sandbox.models import ExecResult

from helpers import create_sandbox, remove_sandbox, shell


class TestCreateSandboxLimitClamping:
    """Verify that sandbox_create clamps limits to configured maximums."""

    async def test_time_limit_clamped_to_max(self, client: httpx.AsyncClient):
        sb = await create_sandbox(client, time_limit=999999)
        try:
            assert sb["config"]["time_limit"] == 3600
        finally:
            await remove_sandbox(client, sb["id"])

    async def test_memory_limit_clamped_to_max(self, client: httpx.AsyncClient):
        sb = await create_sandbox(client, memory_limit=999999)
        try:
            assert sb["config"]["memory_limit"] == 8192
        finally:
            await remove_sandbox(client, sb["id"])

    async def test_pids_limit_clamped_to_max(self, client: httpx.AsyncClient):
        sb = await create_sandbox(client, pids_limit=999999)
        try:
            assert sb["config"]["pids_limit"] == 1024
        finally:
            await remove_sandbox(client, sb["id"])

    async def test_all_limits_clamped(self, client: httpx.AsyncClient):
        sb = await create_sandbox(
            client, time_limit=999999, memory_limit=999999, pids_limit=999999
        )
        try:
            assert sb["config"]["time_limit"] == 3600
            assert sb["config"]["memory_limit"] == 8192
            assert sb["config"]["pids_limit"] == 1024
        finally:
            await remove_sandbox(client, sb["id"])

    async def test_limits_below_max_unchanged(self, client: httpx.AsyncClient):
        sb = await create_sandbox(
            client, time_limit=10, memory_limit=128, pids_limit=32
        )
        try:
            assert sb["config"]["time_limit"] == 10
            assert sb["config"]["memory_limit"] == 128
            assert sb["config"]["pids_limit"] == 32
        finally:
            await remove_sandbox(client, sb["id"])

    async def test_limits_at_max_unchanged(self, client: httpx.AsyncClient):
        sb = await create_sandbox(
            client, time_limit=3600, memory_limit=8192, pids_limit=1024
        )
        try:
            assert sb["config"]["time_limit"] == 3600
            assert sb["config"]["memory_limit"] == 8192
            assert sb["config"]["pids_limit"] == 1024
        finally:
            await remove_sandbox(client, sb["id"])

    async def test_none_limits_use_defaults(self, client: httpx.AsyncClient):
        sb = await create_sandbox(client)
        try:
            assert sb["config"]["time_limit"] == 30
            assert sb["config"]["memory_limit"] == 256
            assert sb["config"]["pids_limit"] == 64
        finally:
            await remove_sandbox(client, sb["id"])


class TestShellTimeoutClamping:
    """Verify that shell timeout is clamped to max_time_limit."""

    async def test_shell_timeout_clamped(
        self, client: httpx.AsyncClient, sandbox: dict, mock_nsjail_run
    ):
        mock_nsjail_run.return_value = ExecResult(exit_code=0, stdout="ok\n", stderr="")
        await shell(client, sandbox["id"], "echo ok", timeout=999999)
        _, kwargs = mock_nsjail_run.call_args
        assert kwargs["timeout"] == 3600

    async def test_shell_timeout_below_max_unchanged(
        self, client: httpx.AsyncClient, sandbox: dict, mock_nsjail_run
    ):
        mock_nsjail_run.return_value = ExecResult(exit_code=0, stdout="ok\n", stderr="")
        await shell(client, sandbox["id"], "echo ok", timeout=10)
        _, kwargs = mock_nsjail_run.call_args
        assert kwargs["timeout"] == 10

    async def test_shell_timeout_none_passes_none(
        self, client: httpx.AsyncClient, sandbox: dict, mock_nsjail_run
    ):
        mock_nsjail_run.return_value = ExecResult(exit_code=0, stdout="ok\n", stderr="")
        await shell(client, sandbox["id"], "echo ok")
        _, kwargs = mock_nsjail_run.call_args
        assert kwargs["timeout"] is None


class TestValidateLimitsDirectly:
    """Unit-test _validate_limits on the manager directly."""

    def test_clamps_above_max(self, manager: SandboxManager):
        tl, ml, pl = manager._validate_limits(999999, 999999, 999999)
        assert tl == 3600
        assert ml == 8192
        assert pl == 1024

    def test_uses_defaults_for_none(self, manager: SandboxManager):
        tl, ml, pl = manager._validate_limits(None, None, None)
        assert tl == 30
        assert ml == 256
        assert pl == 64

    def test_passes_through_below_max(self, manager: SandboxManager):
        tl, ml, pl = manager._validate_limits(10, 128, 32)
        assert tl == 10
        assert ml == 128
        assert pl == 32

    def test_custom_max_settings(self, settings: AgentjailSettings):
        settings.max_time_limit = 60
        settings.max_memory_limit = 512
        settings.max_pids_limit = 128
        mgr = SandboxManager(settings)
        tl, ml, pl = mgr._validate_limits(100, 1000, 200)
        assert tl == 60
        assert ml == 512
        assert pl == 128
