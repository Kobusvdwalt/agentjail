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
    )


@pytest.fixture
def manager(settings):
    return SandboxManager(settings)


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
