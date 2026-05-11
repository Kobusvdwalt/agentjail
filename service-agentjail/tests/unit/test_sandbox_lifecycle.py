import httpx

from helpers import create_sandbox, remove_sandbox


class TestCreateSandbox:
    async def test_create_sandbox_defaults(self, client: httpx.AsyncClient, sandbox: dict):
        assert sandbox["status"] == "running"
        assert len(sandbox["id"]) > 0
        assert sandbox["config"]["time_limit"] == 30
        assert sandbox["config"]["memory_limit"] == 256
        assert sandbox["config"]["pids_limit"] == 64
        assert sandbox["config"]["cwd"] == "/home"
        assert sandbox["config"]["network"] is False

    async def test_create_sandbox_custom_config(self, client: httpx.AsyncClient):
        sb = await create_sandbox(
            client,
            name="custom",
            time_limit=10,
            memory_limit=128,
            pids_limit=32,
            env={"FOO": "bar"},
            cwd="/tmp",
            network=True,
        )
        try:
            assert sb["config"]["time_limit"] == 10
            assert sb["config"]["memory_limit"] == 128
            assert sb["config"]["pids_limit"] == 32
            assert sb["config"]["env"]["FOO"] == "bar"
            assert sb["config"]["cwd"] == "/tmp"
            assert sb["config"]["network"] is True
        finally:
            await remove_sandbox(client, sb["id"])

    async def test_create_sandbox_with_name(self, client: httpx.AsyncClient):
        sb = await create_sandbox(client, name="named-sandbox")
        try:
            assert sb["name"] == "named-sandbox"
        finally:
            await remove_sandbox(client, sb["id"])


class TestInspectSandbox:
    async def test_inspect_sandbox(self, client: httpx.AsyncClient, sandbox: dict):
        resp = await client.get(f"/sandbox/{sandbox['id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == sandbox["id"]
        assert data["status"] == "running"
        assert data["config"] == sandbox["config"]

    async def test_inspect_nonexistent_sandbox(self, client: httpx.AsyncClient):
        resp = await client.get("/sandbox/nonexistent-uuid")
        assert resp.status_code == 404


class TestListSandboxes:
    async def test_list_sandboxes_contains_created(self, client: httpx.AsyncClient):
        sb1 = await create_sandbox(client, name="list-test-1")
        sb2 = await create_sandbox(client, name="list-test-2")
        try:
            resp = await client.get("/sandbox")
            assert resp.status_code == 200
            ids = [s["id"] for s in resp.json()]
            assert sb1["id"] in ids
            assert sb2["id"] in ids
        finally:
            await remove_sandbox(client, sb1["id"])
            await remove_sandbox(client, sb2["id"])


class TestStopSandbox:
    async def test_stop_sandbox(self, client: httpx.AsyncClient, sandbox: dict):
        resp = await client.post(f"/sandbox/{sandbox['id']}/stop")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "stopped"

        resp = await client.get(f"/sandbox/{sandbox['id']}")
        assert resp.json()["status"] == "stopped"

    async def test_stop_nonexistent_sandbox(self, client: httpx.AsyncClient):
        resp = await client.post("/sandbox/nonexistent-uuid/stop")
        assert resp.status_code == 404

    async def test_stop_already_stopped_sandbox(self, client: httpx.AsyncClient, sandbox: dict):
        await client.post(f"/sandbox/{sandbox['id']}/stop")
        resp = await client.post(f"/sandbox/{sandbox['id']}/stop")
        assert resp.status_code == 200


class TestRemoveSandbox:
    async def test_remove_stopped_sandbox(self, client: httpx.AsyncClient):
        sb = await create_sandbox(client)
        await client.post(f"/sandbox/{sb['id']}/stop")
        resp = await client.delete(f"/sandbox/{sb['id']}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "removed"

        resp = await client.get(f"/sandbox/{sb['id']}")
        assert resp.status_code == 404

    async def test_remove_running_sandbox_without_force(self, client: httpx.AsyncClient, sandbox: dict):
        resp = await client.delete(f"/sandbox/{sandbox['id']}")
        assert resp.status_code == 409

    async def test_remove_running_sandbox_with_force(self, client: httpx.AsyncClient):
        sb = await create_sandbox(client)
        resp = await client.delete(f"/sandbox/{sb['id']}", params={"force": True})
        assert resp.status_code == 200
        assert resp.json()["status"] == "removed"

    async def test_remove_nonexistent_sandbox(self, client: httpx.AsyncClient):
        resp = await client.delete("/sandbox/nonexistent-uuid")
        assert resp.status_code == 404


class TestTimestamps:
    async def test_sandbox_timestamps(self, client: httpx.AsyncClient, sandbox: dict):
        assert sandbox["created_at"] is not None
        assert sandbox["updated_at"] is not None

        await client.post(f"/sandbox/{sandbox['id']}/stop")
        resp = await client.get(f"/sandbox/{sandbox['id']}")
        data = resp.json()
        assert data["updated_at"] >= data["created_at"]


class TestStateEndpoint:
    async def test_state_endpoint(self, client: httpx.AsyncClient, sandbox: dict):
        resp = await client.get("/state")
        assert resp.status_code == 200
        data = resp.json()
        assert data["version"] == 1
        assert sandbox["id"] in data["sandboxes"]

    async def test_state_reflects_removal(self, client: httpx.AsyncClient):
        sb = await create_sandbox(client)
        resp = await client.get("/state")
        assert sb["id"] in resp.json()["sandboxes"]

        await remove_sandbox(client, sb["id"])
        resp = await client.get("/state")
        assert sb["id"] not in resp.json()["sandboxes"]
