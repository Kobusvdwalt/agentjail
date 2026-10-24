import asyncio
import shlex
import sys
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from pydantic import ValidationError

from agentjail.api.app import create_api
from agentjail.config import AgentjailSettings
from agentjail.sandbox.lease import LeaseConflict
from agentjail.sandbox.manager import (
    SandboxCapacityExceeded,
    SandboxManager,
    SandboxNotRunning,
)
from agentjail.sandbox.process import run_process


@pytest_asyncio.fixture
async def real_manager(settings):
    settings.runner = "bare"
    manager = SandboxManager(settings)
    yield manager
    await manager.shutdown()


async def wait_for_file(path: Path):
    async with asyncio.timeout(3):
        while not path.exists():
            await asyncio.sleep(0.005)


@pytest.mark.parametrize(
    "path",
    ["/api/v1/state", "/api/v1/sandbox", "/mcp", "/mcp/", "/docs", "/openapi.json"],
)
async def test_control_plane_requires_authentication(manager, path):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_api(manager)), base_url="http://test"
    ) as client:
        for headers in (
            {},
            {"Authorization": "Bearer wrong"},
            {"Authorization": "Basic abc"},
        ):
            response = await client.get(path, headers=headers)
            assert response.status_code == 401
            assert response.headers["www-authenticate"] == "Bearer"
        assert (await client.get("/health")).json() == {"status": "ok"}


def test_service_fails_closed_without_a_strong_token(settings):
    settings.api_token = None
    with pytest.raises(ValueError, match="AGENTJAIL_API_TOKEN"):
        create_api(SandboxManager(settings))
    with pytest.raises(ValidationError):
        AgentjailSettings(api_token="short")


@pytest.mark.parametrize("field", ["time_limit", "memory_limit", "pids_limit"])
@pytest.mark.parametrize("value", [0, -1])
async def test_resource_limits_must_be_positive(client, field, value):
    assert (await client.post("/sandbox", json={field: value})).status_code == 422


async def test_lease_api_contract_and_cross_workspace_fencing(client):
    a = (await client.post("/sandbox", json={})).json()["id"]
    b = (await client.post("/sandbox", json={})).json()["id"]
    grant = (
        await client.post(f"/sandbox/{a}/lease", json={"lease_seconds": 10})
    ).json()
    assert grant["lease_seconds"] == 10
    token = grant["lease_token"]
    assert (await client.post(f"/sandbox/{a}/lease", json={})).status_code == 409
    assert (
        await client.post(
            f"/sandbox/{b}/shell", json={"command": "true", "lease_token": token}
        )
    ).status_code == 409
    assert (
        await client.post(f"/sandbox/{a}/shell", json={"command": "true"})
    ).status_code == 422
    assert (
        await client.post(
            f"/sandbox/{a}/shell", json={"command": "true", "lease_token": "🚀"}
        )
    ).status_code == 409
    assert (
        await client.post(
            f"/sandbox/{a}/lease/renew",
            json={"lease_token": token, "lease_seconds": 20},
        )
    ).status_code == 200
    state = await client.get("/state")
    assert token not in state.text
    schema = (await client.get("http://test/openapi.json")).json()
    assert "/api/v1/sandbox/{sandbox_id}/lease" in schema["paths"]
    assert schema["components"]["securitySchemes"]["HTTPBearer"]["scheme"] == "bearer"


async def test_stop_kills_children_and_reacquisition_fences_old_token(real_manager):
    manager = real_manager
    sandbox = await manager.sandbox_create()
    grant = await manager.acquire_lease(sandbox.id, 10)
    home = Path(sandbox.root_dir) / "home"
    started, late = home / "started", home / "late"
    command = f"touch {shlex.quote(str(started))}; (sleep 0.3; echo late > {shlex.quote(str(late))}) & wait"
    execution = asyncio.create_task(
        manager.sandbox_shell(sandbox.id, command, lease_token=grant.lease_token)
    )
    await wait_for_file(started)
    await manager.sandbox_stop(sandbox.id)
    assert (await execution).killed
    await asyncio.sleep(0.4)
    assert not late.exists()
    replacement = await manager.acquire_lease(sandbox.id, 10)
    assert replacement.lease_token != grant.lease_token
    with pytest.raises(LeaseConflict):
        await manager.sandbox_shell(sandbox.id, "true", lease_token=grant.lease_token)
    result = await manager.sandbox_shell(
        sandbox.id, "printf recovered", lease_token=replacement.lease_token
    )
    assert result.stdout == "recovered"
    assert started.exists()


async def test_expiry_cancels_execution_without_a_worker(real_manager):
    manager = real_manager
    sandbox = await manager.sandbox_create()
    grant = await manager.acquire_lease(sandbox.id, 1)
    late = Path(sandbox.root_dir) / "home" / "late"
    result = await manager.sandbox_shell(
        sandbox.id,
        f"sleep 1.3; echo late > {shlex.quote(str(late))}",
        lease_token=grant.lease_token,
    )
    assert result.killed or result.timed_out
    await asyncio.sleep(0.4)
    assert not late.exists()
    with pytest.raises((LeaseConflict, SandboxNotRunning)):
        await manager.renew_lease(sandbox.id, grant.lease_token, 10)


async def test_renewal_replaces_expiry_timer(real_manager):
    manager = real_manager
    sandbox = await manager.sandbox_create()
    grant = await manager.acquire_lease(sandbox.id, 1)
    await manager.renew_lease(sandbox.id, grant.lease_token, 10)
    await asyncio.sleep(1.1)
    result = await manager.sandbox_shell(
        sandbox.id, "printf active", lease_token=grant.lease_token
    )
    assert result.stdout == "active"


async def test_shutdown_cancels_registered_processes(real_manager):
    manager = real_manager
    sandbox = await manager.sandbox_create()
    grant = await manager.acquire_lease(sandbox.id, 10)
    started = Path(sandbox.root_dir) / "home" / "started"
    execution = asyncio.create_task(
        manager.sandbox_shell(
            sandbox.id,
            f"touch {shlex.quote(str(started))}; sleep 60",
            lease_token=grant.lease_token,
        )
    )
    await wait_for_file(started)
    await asyncio.wait_for(manager.shutdown(), 3)
    assert (await execution).killed
    assert not manager._active
    assert not manager._leases


async def test_reacquisition_waits_for_previous_execution_cleanup(
    real_manager, monkeypatch
):
    manager = real_manager
    sandbox = await manager.sandbox_create()
    grant = await manager.acquire_lease(sandbox.id, 10)
    started, cleaning, finish_cleanup = (
        asyncio.Event(),
        asyncio.Event(),
        asyncio.Event(),
    )

    async def run_command(*args, **kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await finish_cleanup.wait()

    monkeypatch.setattr(manager.runner, "run_command", run_command)
    execution = asyncio.create_task(
        manager.sandbox_shell(sandbox.id, "true", lease_token=grant.lease_token)
    )
    await started.wait()
    stopping = asyncio.create_task(manager.sandbox_stop(sandbox.id))
    await cleaning.wait()
    acquiring = asyncio.create_task(manager.acquire_lease(sandbox.id, 10))
    await asyncio.sleep(0)
    assert not acquiring.done()
    finish_cleanup.set()
    await stopping
    assert (await execution).killed
    replacement = await acquiring
    assert replacement.lease_token != grant.lease_token


async def test_force_removal_terminates_execution_before_deleting_files(real_manager):
    manager = real_manager
    sandbox = await manager.sandbox_create()
    grant = await manager.acquire_lease(sandbox.id, 10)
    started = Path(sandbox.root_dir) / "home" / "started"
    execution = asyncio.create_task(
        manager.sandbox_shell(
            sandbox.id,
            f"touch {shlex.quote(str(started))}; sleep 60",
            lease_token=grant.lease_token,
        )
    )
    await wait_for_file(started)
    await asyncio.wait_for(manager.sandbox_remove(sandbox.id, force=True), 3)
    assert (await execution).killed
    assert not Path(sandbox.root_dir).exists()


async def test_cancellation_during_spawn_does_not_leave_a_process(
    monkeypatch, tmp_path
):
    original = asyncio.create_subprocess_exec
    spawned, release = asyncio.Event(), asyncio.Event()
    processes = []

    async def delayed_spawn(*args, **kwargs):
        process = await original(*args, **kwargs)
        processes.append(process)
        spawned.set()
        await release.wait()
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", delayed_spawn)
    late = tmp_path / "late"
    execution = asyncio.create_task(
        run_process(
            ["/bin/sh", "-c", f"sleep 0.3; echo late > {shlex.quote(str(late))}"],
            timeout=10,
            output_limit=128,
        )
    )
    await spawned.wait()
    execution.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(execution, 3)
    await asyncio.sleep(0.4)
    assert processes[0].returncode is not None
    assert not late.exists()


async def test_captured_output_is_bounded_while_both_streams_drain():
    result = await run_process(
        [
            sys.executable,
            "-c",
            "import sys; sys.stdout.write('a'*2000000+'z'); sys.stderr.write('b'*2000000+'y')",
        ],
        timeout=5,
        output_limit=8192,
    )
    assert result.exit_code == 0
    assert result.stdout_truncated and result.stderr_truncated
    assert len(result.stdout) == len(result.stderr) == 8192
    assert result.stdout.endswith("z") and result.stderr.endswith("y")


async def test_capacity_limit_rejects_instead_of_queueing(real_manager):
    manager = real_manager
    manager.settings.max_active_commands = 1
    sandbox = await manager.sandbox_create()
    grant = await manager.acquire_lease(sandbox.id, 10)
    started = Path(sandbox.root_dir) / "home" / "started"
    execution = asyncio.create_task(
        manager.sandbox_shell(
            sandbox.id,
            f"touch {shlex.quote(str(started))}; sleep 60",
            lease_token=grant.lease_token,
        )
    )
    await wait_for_file(started)
    with pytest.raises(SandboxCapacityExceeded):
        await manager.sandbox_shell(sandbox.id, "true", lease_token=grant.lease_token)
    await manager.sandbox_stop(sandbox.id)
    assert (await execution).killed


async def test_service_restart_invalidates_leases_but_keeps_files(settings):
    settings.runner = "bare"
    first = SandboxManager(settings)
    sandbox = await first.sandbox_create()
    grant = await first.acquire_lease(sandbox.id, 10)
    await first.sandbox_fs_write(sandbox.id, "/home/proof", "saved")
    await first.shutdown()
    replacement = SandboxManager(settings)
    try:
        with pytest.raises(LeaseConflict):
            await replacement.sandbox_shell(
                sandbox.id, "true", lease_token=grant.lease_token
            )
        current = await replacement.acquire_lease(sandbox.id, 10)
        assert current.lease_token != grant.lease_token
        assert (
            await replacement.sandbox_fs_download(sandbox.id, "/home/proof")
        ).read_text() == "saved"
    finally:
        await replacement.shutdown()
