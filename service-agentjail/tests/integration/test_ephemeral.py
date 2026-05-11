import httpx

from helpers import create_sandbox, remove_sandbox, shell


class TestShellExecution:
    async def test_shell_echo(self, client: httpx.AsyncClient):
        sb = await create_sandbox(client)
        result = await shell(client, sb["id"], "echo hello")
        assert result["exit_code"] == 0
        assert "hello" in result["stdout"]
        await remove_sandbox(client, sb["id"])

    async def test_shell_exit_code(self, client: httpx.AsyncClient):
        sb = await create_sandbox(client)
        result = await shell(client, sb["id"], "exit 42")
        assert result["exit_code"] == 42
        await remove_sandbox(client, sb["id"])

    async def test_shell_stderr(self, client: httpx.AsyncClient):
        sb = await create_sandbox(client)
        result = await shell(client, sb["id"], "echo err >&2")
        assert "err" in result["stderr"]
        await remove_sandbox(client, sb["id"])

    async def test_shell_combined_output(self, client: httpx.AsyncClient):
        sb = await create_sandbox(client)
        result = await shell(client, sb["id"], "echo out && echo err >&2")
        assert "out" in result["stdout"]
        assert "err" in result["stderr"]
        await remove_sandbox(client, sb["id"])

    async def test_shell_timeout(self, client: httpx.AsyncClient):
        sb = await create_sandbox(client, time_limit=2)
        result = await shell(client, sb["id"], "sleep 60")
        assert result["timed_out"] or result["exit_code"] != 0
        await remove_sandbox(client, sb["id"])

    async def test_shell_multiline_command(self, client: httpx.AsyncClient):
        sb = await create_sandbox(client)
        result = await shell(client, sb["id"], "for i in 1 2 3; do echo $i; done")
        assert result["exit_code"] == 0
        for n in ["1", "2", "3"]:
            assert n in result["stdout"]
        await remove_sandbox(client, sb["id"])

    async def test_shell_pipe(self, client: httpx.AsyncClient):
        sb = await create_sandbox(client)
        result = await shell(client, sb["id"], "echo hello | tr a-z A-Z")
        assert "HELLO" in result["stdout"]
        await remove_sandbox(client, sb["id"])

    async def test_shell_binary_not_found(self, client: httpx.AsyncClient):
        sb = await create_sandbox(client)
        result = await shell(client, sb["id"], "/nonexistent/binary")
        assert result["exit_code"] != 0
        await remove_sandbox(client, sb["id"])
