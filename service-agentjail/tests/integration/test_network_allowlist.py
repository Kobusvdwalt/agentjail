"""Allowlisted egress through real nsjail: the jail reaches only what is listed."""

import time
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
def config_file(tmp_path_factory):
    path = tmp_path_factory.mktemp("config") / "agentjail.yaml"
    path.write_text(
        "network_allow:\n"
        f"  - {TARGET}:9000\n"
        "  - 169.254.169.254\n"
        "network_allow_private: true\n"
    )
    path.chmod(0o644)
    return path


@pytest.fixture(scope="module")
def egress_container(image, config_file):
    with (
        DockerContainer(image)
        .with_exposed_ports(8000)
        .with_env_file(str(SERVICE_DIR / "default.env"))
        .with_env("AGENTJAIL_API_TOKEN", TOKEN)
        # The allowlist comes from the config file at its default location.
        .with_volume_mapping(str(config_file), "/etc/agentjail/agentjail.yaml", "ro")
        .with_kwargs(privileged=True, user="root", hostname=TARGET)
        .waiting_for(
            LogMessageWaitStrategy("Application startup complete").with_startup_timeout(
                60
            )
        )
    ) as container:
        # A server outside the jail, on the container's own (private) address.
        wrapped = container.get_wrapped_container()
        wrapped.exec_run(
            ["python3", "-m", "http.server", "9000", "--bind", "0.0.0.0"],
            detach=True,
            workdir="/tmp",
        )
        probe = f"import socket; socket.create_connection(('{TARGET}', 9000), 1)"
        deadline = time.monotonic() + 30
        while wrapped.exec_run(["python3", "-c", probe]).exit_code != 0:
            if time.monotonic() > deadline:
                raise RuntimeError(f"the test server on {TARGET}:9000 did not start")
            time.sleep(0.2)
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
        f"curl -sS -w '\\n%{{http_code}}' http://{TARGET}:9000/",
    )
    body, _, status = result["stdout"].rpartition("\n")
    assert status == "200", body + result["stderr"]


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
