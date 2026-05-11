import httpx

from agentjail.sandbox.models import ExecResult
from helpers import create_sandbox, exec_cmd, remove_sandbox, shell


class TestShell:
    async def test_shell_echo(self, client: httpx.AsyncClient, sandbox: dict, mock_nsjail_run):
        mock_nsjail_run.return_value = ExecResult(exit_code=0, stdout="hello\n", stderr="")
        result = await shell(client, sandbox["id"], "echo hello")
        assert result["exit_code"] == 0
        assert "hello" in result["stdout"]

    async def test_shell_exit_code(self, client: httpx.AsyncClient, sandbox: dict, mock_nsjail_run):
        mock_nsjail_run.return_value = ExecResult(exit_code=7, stdout="", stderr="")
        result = await shell(client, sandbox["id"], "exit 7")
        assert result["exit_code"] == 7

    async def test_shell_stderr(self, client: httpx.AsyncClient, sandbox: dict, mock_nsjail_run):
        mock_nsjail_run.return_value = ExecResult(exit_code=0, stdout="", stderr="err\n")
        result = await shell(client, sandbox["id"], "echo err >&2")
        assert "err" in result["stderr"]

    async def test_shell_pipe(self, client: httpx.AsyncClient, sandbox: dict, mock_nsjail_run):
        mock_nsjail_run.return_value = ExecResult(exit_code=0, stdout="2\n", stderr="")
        result = await shell(client, sandbox["id"], "echo hello world | wc -w")
        assert result["stdout"].strip() == "2"

    async def test_shell_env_from_config(self, client: httpx.AsyncClient, mock_nsjail_run):
        sb = await create_sandbox(client, env={"SANDBOX_VAR": "value123"})
        try:
            mock_nsjail_run.return_value = ExecResult(exit_code=0, stdout="value123\n", stderr="")
            result = await shell(client, sb["id"], "echo $SANDBOX_VAR")
            assert "value123" in result["stdout"]
        finally:
            await remove_sandbox(client, sb["id"])

    async def test_shell_timeout(self, client: httpx.AsyncClient, sandbox: dict, mock_nsjail_run):
        mock_nsjail_run.return_value = ExecResult(exit_code=-1, stdout="", stderr="", timed_out=True)
        result = await shell(client, sandbox["id"], "sleep 60", timeout=2)
        assert result["timed_out"] or result["exit_code"] != 0

    async def test_shell_cwd_default(self, client: httpx.AsyncClient, sandbox: dict, mock_nsjail_run):
        mock_nsjail_run.return_value = ExecResult(exit_code=0, stdout="/home\n", stderr="")
        result = await shell(client, sandbox["id"], "pwd")
        assert result["stdout"].strip() == "/home"

    async def test_shell_write_and_read_file(self, client: httpx.AsyncClient, sandbox: dict, mock_nsjail_run):
        mock_nsjail_run.side_effect = [
            ExecResult(exit_code=0, stdout="", stderr=""),
            ExecResult(exit_code=0, stdout="content\n", stderr=""),
        ]
        await shell(client, sandbox["id"], "echo content > /home/test.txt")
        result = await shell(client, sandbox["id"], "cat /home/test.txt")
        assert "content" in result["stdout"]

    async def test_shell_file_persists_across_calls(self, client: httpx.AsyncClient, sandbox: dict, mock_nsjail_run):
        mock_nsjail_run.side_effect = [
            ExecResult(exit_code=0, stdout="", stderr=""),
            ExecResult(exit_code=0, stdout="data\n", stderr=""),
        ]
        await shell(client, sandbox["id"], "echo data > /home/persist.txt")
        result = await shell(client, sandbox["id"], "cat /home/persist.txt")
        assert "data" in result["stdout"]

    async def test_shell_multiline_script(self, client: httpx.AsyncClient, sandbox: dict, mock_nsjail_run):
        mock_nsjail_run.return_value = ExecResult(exit_code=0, stdout="3\n", stderr="")
        result = await shell(client, sandbox["id"], "x=1; y=2; echo $((x+y))")
        assert result["stdout"].strip() == "3"


class TestExec:
    async def test_exec_binary(self, client: httpx.AsyncClient, sandbox: dict, mock_nsjail_run):
        mock_nsjail_run.return_value = ExecResult(exit_code=0, stdout="hello world\n", stderr="")
        result = await exec_cmd(client, sandbox["id"], "/bin/echo", args=["hello", "world"])
        assert result["exit_code"] == 0
        assert "hello world" in result["stdout"]

    async def test_exec_ls(self, client: httpx.AsyncClient, sandbox: dict, mock_nsjail_run):
        mock_nsjail_run.return_value = ExecResult(exit_code=0, stdout="total 0\n", stderr="")
        result = await exec_cmd(client, sandbox["id"], "/bin/ls", args=["-la", "/home"])
        assert result["exit_code"] == 0
        assert len(result["stdout"]) > 0

    async def test_exec_with_cwd(self, client: httpx.AsyncClient, sandbox: dict, mock_nsjail_run):
        mock_nsjail_run.return_value = ExecResult(exit_code=0, stdout="/tmp\n", stderr="")
        result = await exec_cmd(client, sandbox["id"], "/bin/pwd", cwd="/tmp")
        assert result["stdout"].strip() == "/tmp"

    async def test_exec_with_env(self, client: httpx.AsyncClient, sandbox: dict, mock_nsjail_run):
        mock_nsjail_run.return_value = ExecResult(exit_code=0, stdout="override\n", stderr="")
        result = await exec_cmd(
            client, sandbox["id"], "/bin/sh", args=["-c", "echo $X"], env={"X": "override"}
        )
        assert "override" in result["stdout"]

    async def test_exec_with_timeout(self, client: httpx.AsyncClient, sandbox: dict, mock_nsjail_run):
        mock_nsjail_run.return_value = ExecResult(exit_code=-1, stdout="", stderr="", timed_out=True)
        result = await exec_cmd(client, sandbox["id"], "/bin/sleep", args=["60"], timeout=2)
        assert result["timed_out"] or result["exit_code"] != 0

    async def test_exec_nonexistent_binary(self, client: httpx.AsyncClient, sandbox: dict, mock_nsjail_run):
        mock_nsjail_run.return_value = ExecResult(exit_code=127, stdout="", stderr="not found\n")
        result = await exec_cmd(client, sandbox["id"], "/nonexistent/binary")
        assert result["exit_code"] != 0


class TestErrorCases:
    async def test_exec_nonexistent_sandbox(self, client: httpx.AsyncClient):
        resp = await client.post("/sandbox/nonexistent-uuid/exec", json={"command": "/bin/echo"})
        assert resp.status_code == 404

    async def test_shell_nonexistent_sandbox(self, client: httpx.AsyncClient):
        resp = await client.post("/sandbox/nonexistent-uuid/shell", json={"command": "echo hi"})
        assert resp.status_code == 404

    async def test_exec_stopped_sandbox(self, client: httpx.AsyncClient, sandbox: dict):
        await client.post(f"/sandbox/{sandbox['id']}/stop")
        resp = await client.post(f"/sandbox/{sandbox['id']}/exec", json={"command": "/bin/echo"})
        assert resp.status_code == 409

    async def test_shell_stopped_sandbox(self, client: httpx.AsyncClient, sandbox: dict):
        await client.post(f"/sandbox/{sandbox['id']}/stop")
        resp = await client.post(f"/sandbox/{sandbox['id']}/shell", json={"command": "echo hi"})
        assert resp.status_code == 409
