import sys
from pathlib import Path
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).parent))

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport

from agentjail.api.app import create_api
from agentjail.config import AgentjailSettings
from agentjail.sandbox.manager import SandboxManager
from agentjail.sandbox.models import ExecResult


@pytest.fixture
def settings(tmp_path):
    return AgentjailSettings(
        sandbox_base_dir=tmp_path / "sandboxes",
        state_file=tmp_path / "state.json",
        nsjail_bin="/dev/null",
        api_token="unit-test-token-379-not-a-secret-value",
    )


@pytest_asyncio.fixture
async def manager(settings):
    manager = SandboxManager(settings)
    yield manager
    await manager.shutdown()


@pytest.fixture
def mock_nsjail_run(manager):
    mock = AsyncMock(return_value=ExecResult(exit_code=0, stdout="", stderr=""))
    manager.runner.run_command = mock
    return mock


@pytest_asyncio.fixture
async def client(manager, mock_nsjail_run):
    app = create_api(manager)
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test/api/v1",
        timeout=60.0,
        headers={
            "Authorization": f"Bearer {manager.settings.api_token.get_secret_value()}"
        },
    ) as c:
        yield c


@pytest_asyncio.fixture
async def sandbox(client):
    resp = await client.post("/sandbox", json={})
    assert resp.status_code == 200
    data = resp.json()
    yield data
    await client.delete(f"/sandbox/{data['id']}", params={"force": True})


@pytest_asyncio.fixture
async def sandbox_with_network(client):
    resp = await client.post("/sandbox", json={"network": True})
    assert resp.status_code == 200
    data = resp.json()
    yield data
    await client.delete(f"/sandbox/{data['id']}", params={"force": True})
