import httpx

from agentjail.sandbox.models import ExecResult


class TestEphemeralRun:
    async def test_ephemeral_echo(self, client: httpx.AsyncClient, mock_nsjail_run):
        mock_nsjail_run.return_value = ExecResult(exit_code=0, stdout="hello\n", stderr="")
        resp = await client.post("/sandbox/run", json={"command": "echo hello"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["result"]["exit_code"] == 0
        assert "hello" in data["result"]["stdout"]
        assert len(data["sandbox_id"]) > 0

    async def test_ephemeral_exit_code(self, client: httpx.AsyncClient, mock_nsjail_run):
        mock_nsjail_run.return_value = ExecResult(exit_code=42, stdout="", stderr="")
        resp = await client.post("/sandbox/run", json={"command": "exit 42"})
        data = resp.json()
        assert data["result"]["exit_code"] == 42

    async def test_ephemeral_stderr(self, client: httpx.AsyncClient, mock_nsjail_run):
        mock_nsjail_run.return_value = ExecResult(exit_code=0, stdout="", stderr="err\n")
        resp = await client.post("/sandbox/run", json={"command": "echo err >&2"})
        data = resp.json()
        assert "err" in data["result"]["stderr"]

    async def test_ephemeral_combined_output(self, client: httpx.AsyncClient, mock_nsjail_run):
        mock_nsjail_run.return_value = ExecResult(exit_code=0, stdout="out\n", stderr="err\n")
        resp = await client.post("/sandbox/run", json={"command": "echo out && echo err >&2"})
        data = resp.json()
        assert "out" in data["result"]["stdout"]
        assert "err" in data["result"]["stderr"]

    async def test_ephemeral_with_env(self, client: httpx.AsyncClient, mock_nsjail_run):
        mock_nsjail_run.return_value = ExecResult(exit_code=0, stdout="secret\n", stderr="")
        resp = await client.post("/sandbox/run", json={"command": "echo $MY_VAR", "env": {"MY_VAR": "secret"}})
        data = resp.json()
        assert "secret" in data["result"]["stdout"]

    async def test_ephemeral_custom_time_limit(self, client: httpx.AsyncClient, mock_nsjail_run):
        mock_nsjail_run.return_value = ExecResult(exit_code=0, stdout="done\n", stderr="")
        resp = await client.post("/sandbox/run", json={"command": "sleep 2 && echo done", "time_limit": 10})
        data = resp.json()
        assert data["result"]["exit_code"] == 0
        assert "done" in data["result"]["stdout"]

    async def test_ephemeral_timeout(self, client: httpx.AsyncClient, mock_nsjail_run):
        mock_nsjail_run.return_value = ExecResult(exit_code=-1, stdout="", stderr="", timed_out=True)
        resp = await client.post("/sandbox/run", json={"command": "sleep 60", "time_limit": 2})
        data = resp.json()
        result = data["result"]
        assert result["timed_out"] or result["exit_code"] != 0

    async def test_ephemeral_custom_memory_limit(self, client: httpx.AsyncClient, mock_nsjail_run):
        mock_nsjail_run.return_value = ExecResult(exit_code=0, stdout="ok\n", stderr="")
        resp = await client.post("/sandbox/run", json={"command": "echo ok", "memory_limit": 64})
        data = resp.json()
        assert data["result"]["exit_code"] == 0

    async def test_ephemeral_cleanup_no_persist(self, client: httpx.AsyncClient, mock_nsjail_run):
        mock_nsjail_run.return_value = ExecResult(exit_code=0, stdout="hello\n", stderr="")
        resp = await client.post("/sandbox/run", json={"command": "echo hello"})
        sandbox_id = resp.json()["sandbox_id"]
        resp = await client.get(f"/sandbox/{sandbox_id}")
        assert resp.status_code == 404

    async def test_ephemeral_multiline_command(self, client: httpx.AsyncClient, mock_nsjail_run):
        mock_nsjail_run.return_value = ExecResult(exit_code=0, stdout="1\n2\n3\n", stderr="")
        resp = await client.post("/sandbox/run", json={"command": "for i in 1 2 3; do echo $i; done"})
        data = resp.json()
        assert data["result"]["exit_code"] == 0
        for n in ["1", "2", "3"]:
            assert n in data["result"]["stdout"]

    async def test_ephemeral_pipe(self, client: httpx.AsyncClient, mock_nsjail_run):
        mock_nsjail_run.return_value = ExecResult(exit_code=0, stdout="HELLO\n", stderr="")
        resp = await client.post("/sandbox/run", json={"command": "echo hello | tr a-z A-Z"})
        data = resp.json()
        assert "HELLO" in data["result"]["stdout"]

    async def test_ephemeral_binary_not_found(self, client: httpx.AsyncClient, mock_nsjail_run):
        mock_nsjail_run.return_value = ExecResult(exit_code=127, stdout="", stderr="/nonexistent/binary: not found\n")
        resp = await client.post("/sandbox/run", json={"command": "/nonexistent/binary"})
        data = resp.json()
        assert data["result"]["exit_code"] != 0
