import sys
from pathlib import Path
import os
import tempfile

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
def resources_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        resources = Path(tmpdir)
        # Ensure world-readable so nsjail's sandboxed uid 1000 can access
        # the bind-mounted files (temp dirs default to mode 0700 on Linux).
        os.chmod(tmpdir, 0o755)
        (resources / "hello.txt").write_text("hello from resources")
        (resources / "subdir").mkdir()
        (resources / "subdir" / "nested.txt").write_text("nested file")
        skill_dir = resources / "pdf-extractor"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: pdf-extractor\ndescription: Extract text from PDFs\n---\n# PDF Extractor\n"
        )
        yield str(resources)


TOKEN = "integration-test-token-379-not-a-secret"


def _service_container(image: str, user: str) -> DockerContainer:
    return (
        DockerContainer(image)
        .with_exposed_ports(8000)
        .with_env_file(str(Path(SERVICE_DIR) / "default.env"))
        .with_env("AGENTJAIL_API_TOKEN", TOKEN)
        .with_kwargs(
            privileged=True,
            user=user,
        )
        .waiting_for(
            LogMessageWaitStrategy("Application startup complete").with_startup_timeout(
                60
            )
        )
    )


def _base_url(container: DockerContainer) -> str:
    host = container.get_container_host_ip()
    port = container.get_exposed_port(8000)
    return f"http://{host}:{port}/api/v1"


@pytest.fixture(scope="session")
def container(image, resources_dir):
    with _service_container(image, "root").with_volume_mapping(
        resources_dir, "/var/lib/agentjail/resources", "ro"
    ) as c:
        yield c


@pytest.fixture(scope="session")
def service_user_container(image):
    """The service as the image's non-root user, as deployments run it.

    Running as root hides bugs: the jail's uid 1000 then maps to the owner of
    host files such as /dev/null, which a non-root service never is.
    """
    with _service_container(image, "service") as c:
        yield c


@pytest_asyncio.fixture
async def service_user_client(service_user_container):
    async with httpx.AsyncClient(
        base_url=_base_url(service_user_container),
        timeout=60.0,
        headers={"Authorization": f"Bearer {TOKEN}"},
    ) as c:
        yield c


@pytest.fixture(scope="session")
def base_url(container):
    return _base_url(container)


@pytest_asyncio.fixture
async def client(base_url):
    async with httpx.AsyncClient(
        base_url=base_url,
        timeout=60.0,
        headers={"Authorization": f"Bearer {TOKEN}"},
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
