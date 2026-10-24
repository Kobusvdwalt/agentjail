import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from agentjail.sandbox.lease import LeaseConflict


async def test_workspace_creation_is_idempotent_and_configuration_is_immutable(
    client, manager
):
    workspace_id = str(uuid4())
    path = f"/sandbox/{workspace_id}"
    config = {"network": False, "resources": [], "env": {}}
    first = await client.put(path, json=config)
    assert first.status_code == 200
    home = Path(first.json()["root_dir"]) / "home"
    (home / "saved").write_text("persistent")
    await manager.sandbox_stop(workspace_id)
    repeated = await client.put(path, json=config)
    assert repeated.status_code == 200
    assert repeated.json()["status"] == "stopped"
    assert (home / "saved").read_text() == "persistent"
    assert len(await manager.sandbox_list()) == 1
    assert (await client.put(path, json={**config, "network": True})).status_code == 409
    assert (await client.put("/sandbox/../invalid", json=config)).status_code != 200


async def test_absolute_authorization_caps_acquire_and_renew(client):
    workspace_id = (await client.post("/sandbox", json={})).json()["id"]
    path = f"/sandbox/{workspace_id}/lease"
    bound = datetime.now(timezone.utc) + timedelta(seconds=2)
    grant = await client.post(
        path, json={"lease_seconds": 120, "not_after": bound.isoformat()}
    )
    assert grant.status_code == 200
    data = grant.json()
    assert datetime.fromisoformat(data["expires_at"]) <= bound
    renewed = await client.post(
        f"{path}/renew", json={"lease_token": data["lease_token"], "lease_seconds": 300}
    )
    assert renewed.status_code == 200
    assert datetime.fromisoformat(renewed.json()["expires_at"]) <= bound
    expired = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    assert (
        await client.post(
            f"{path}/renew",
            json={"lease_token": data["lease_token"], "not_after": expired},
        )
    ).status_code == 409
    assert (
        await client.post(path, json={"not_after": "2026-01-01T00:00:00"})
    ).status_code == 422


async def test_expired_authorization_cannot_acquire_even_after_cleanup(manager):
    workspace = await manager.sandbox_create()
    with pytest.raises(LeaseConflict):
        await manager.acquire_lease(
            workspace.id, 30, datetime.now(timezone.utc) - timedelta(seconds=1)
        )
    assert workspace.id not in manager._leases


async def test_stale_release_cannot_stop_a_new_owner(client):
    workspace_id = (await client.post("/sandbox", json={})).json()["id"]
    path = f"/sandbox/{workspace_id}/lease"
    old = (await client.post(path, json={})).json()["lease_token"]
    assert (
        await client.post(f"{path}/release", json={"lease_token": old})
    ).status_code == 200
    new = (await client.post(path, json={})).json()["lease_token"]
    assert new != old
    assert (
        await client.post(f"{path}/release", json={"lease_token": old})
    ).status_code == 409
    assert (
        await client.post(f"{path}/renew", json={"lease_token": new})
    ).status_code == 200


async def test_absolute_expiry_releases_without_a_worker(manager):
    workspace = await manager.sandbox_create()
    grant = await manager.acquire_lease(
        workspace.id, 120, datetime.now(timezone.utc) + timedelta(milliseconds=50)
    )
    await asyncio.sleep(0.1)
    assert (await manager.sandbox_inspect(workspace.id)).status == "stopped"
    with pytest.raises(LeaseConflict):
        await manager.release_lease(workspace.id, grant.lease_token)


async def test_reprovision_waits_for_removal_cleanup(manager, monkeypatch):
    workspace_id = uuid4()
    old = await manager.sandbox_create(workspace_id=workspace_id)
    await manager.sandbox_stop(old.id)
    cleaning, finish = asyncio.Event(), asyncio.Event()
    revoke = manager._revoke_lease

    async def delayed_revoke(sandbox_id):
        await revoke(sandbox_id)
        cleaning.set()
        await finish.wait()

    monkeypatch.setattr(manager, "_revoke_lease", delayed_revoke)
    removing = asyncio.create_task(manager.sandbox_remove(old.id))
    await cleaning.wait()
    ensuring = asyncio.create_task(manager.sandbox_create(workspace_id=workspace_id))
    await asyncio.sleep(0)
    assert not ensuring.done()
    finish.set()
    await removing
    fresh = await ensuring
    assert Path(fresh.root_dir).is_dir()
    assert (await manager.sandbox_inspect(fresh.id)).id == old.id
