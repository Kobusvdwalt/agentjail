import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import httpx
import pytest
import pytest_asyncio
from testcontainers.core.container import DockerContainer
from testcontainers.core.image import DockerImage
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

SERVICE_DIR = str(Path(__file__).resolve().parent.parent.parent)


@pytest.fixture(scope="session")
def image():
    with DockerImage(
        path=SERVICE_DIR,
        dockerfile_path="dev.dockerfile",
        tag="agentjail-test:latest",
        clean_up=True,
    ) as img:
        yield str(img)


@pytest.fixture(scope="session")
def container(image):
    with (
        DockerContainer(image)
        .with_exposed_ports(8000)
        .with_env_file(str(Path(SERVICE_DIR) / "default.env"))
        .with_kwargs(
            cap_add=["SYS_ADMIN"],
            security_opt=["apparmor=unconfined", "seccomp=unconfined"],
        )
        .waiting_for(
            LogMessageWaitStrategy("Application startup complete").with_startup_timeout(
                60
            )
        )
    ) as c:
        yield c


@pytest.fixture(scope="session")
def base_url(container):
    host = container.get_container_host_ip()
    port = container.get_exposed_port(8000)
    return f"http://{host}:{port}/api/v1"


@pytest_asyncio.fixture
async def client(base_url):
    async with httpx.AsyncClient(base_url=base_url, timeout=60.0) as c:
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
