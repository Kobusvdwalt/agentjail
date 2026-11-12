"""Allowlisted egress through real nsjail: the jail reaches only what is listed."""

import json
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from helpers import create_sandbox, remove_sandbox, shell
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

SERVICE_DIR = Path(__file__).resolve().parent.parent.parent
TOKEN = "integration-test-token-379-not-a-secret"
TARGET = "egress-target"


@pytest.fixture(scope="module")
def egress_container(image):
    with (
        DockerContainer(image)
        .with_exposed_ports(8000)
        .with_env_file(str(SERVICE_DIR / "default.env"))
        .with_env("AGENTJAIL_API_TOKEN", TOKEN)
        .with_env(
            "AGENTJAIL_NETWORK_ALLOW", json.dumps([f"{TARGET}:9000", "169.254.169.254"])
        )
        .with_env("AGENTJAIL_NETWORK_ALLOW_PRIVATE", "true")
        .with_kwargs(privileged=True, user="root", hostname=TARGET)
        .waiting_for(
            LogMessageWaitStrategy("Application startup complete").with_startup_timeout(
                60
            )
        )
    ) as container:
        # A server outside the jail, on the container's own (private) address.
        container.get_wrapped_container().exec_run(
            ["python3", "-m", "http.server", "9000", "--bind", "0.0.0.0"],
            detach=True,
            workdir="/tmp",
        )
        yield container


@pytest_asyncio.fixture
async def egress_client(egress_container):
    host = egress_container.get_container_host_ip()
    port = egress_container.get_exposed_port(8000)
    async with httpx.AsyncClient(
        base_url=f"http://{host}:{port}/api/v1",
        timeout=60.0,
        headers={"Authorization": f"Bearer {TOKEN}"},
    ) as client:
        yield client


@pytest_asyncio.fixture
async def offline_sandbox(egress_client):
    sandbox = await create_sandbox(egress_client)
    yield sandbox
    await remove_sandbox(egress_client, sandbox["id"])


async def test_an_allowlisted_host_is_reachable(egress_client, offline_sandbox):
    result = await shell(
        egress_client,
        offline_sandbox["id"],
        f"curl -sS -o /dev/null -w '%{{http_code}}' http://{TARGET}:9000/",
    )
    assert result["stdout"] == "200", result["stderr"]


async def test_the_proxy_is_announced_in_the_environment(
    egress_client, offline_sandbox
):
    result = await shell(egress_client, offline_sandbox["id"], "echo $HTTPS_PROXY")
    assert result["stdout"].strip() == "http://127.0.0.1:3128"


async def test_another_port_on_the_same_host_is_refused(egress_client, offline_sandbox):
    result = await shell(
        egress_client, offline_sandbox["id"], f"curl -sS http://{TARGET}:9001/"
    )
    assert f"{TARGET}:9001 is not in the sandbox network allowlist" in result["stdout"]


async def test_https_to_an_unlisted_host_is_refused(egress_client, offline_sandbox):
    result = await shell(
        egress_client, offline_sandbox["id"], "curl -sS https://example.com/"
    )
    assert result["exit_code"] != 0
    assert "403" in result["stderr"]


async def test_metadata_is_refused_even_when_listed(egress_client, offline_sandbox):
    result = await shell(
        egress_client, offline_sandbox["id"], "curl -sS http://169.254.169.254/"
    )
    assert "resolves to an address sandboxes cannot reach" in result["stdout"]


async def test_bypassing_the_proxy_finds_no_network(egress_client, offline_sandbox):
    result = await shell(
        egress_client,
        offline_sandbox["id"],
        f"curl -sS --noproxy '*' --max-time 5 http://{TARGET}:9000/",
    )
    assert result["exit_code"] != 0
