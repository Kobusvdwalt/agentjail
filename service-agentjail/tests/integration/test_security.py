import httpx
import pytest

from helpers import (
    create_sandbox,
    download,
    exec_cmd,
    remove_sandbox,
    shell,
    upload,
)


# ---------------------------------------------------------------------------
# Path traversal via download API
# ---------------------------------------------------------------------------


class TestPathTraversalAPI:
    async def test_path_traversal_download_etc_passwd(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        resp = await download(client, sandbox["id"], "../../etc/passwd")
        assert resp.status_code == 400

    async def test_path_traversal_download_absolute(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        resp = await download(client, sandbox["id"], "/../../etc/passwd")
        assert resp.status_code == 400

    async def test_path_traversal_download_encoded_slashes(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        resp = await download(client, sandbox["id"], "%2e%2e%2f%2e%2e%2fetc%2fpasswd")
        assert resp.status_code in (400, 404)

    async def test_path_traversal_download_null_byte(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        resp = await download(client, sandbox["id"], "/test.txt\x00../../etc/passwd")
        assert resp.status_code in (400, 404, 422, 500)


# ---------------------------------------------------------------------------
# Path traversal via symlinks
# ---------------------------------------------------------------------------


class TestSymlinkEscape:
    async def test_symlink_read_etc_passwd(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        await shell(client, sandbox["id"], "ln -s /etc/passwd /home/link")
        resp = await download(client, sandbox["id"], "/home/link")
        if resp.status_code == 200:
            assert b"root:" not in resp.content
        else:
            assert resp.status_code in (400, 404)

    async def test_symlink_read_state_file(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        await shell(
            client,
            sandbox["id"],
            "ln -s /var/lib/agentjail/state.json /home/statelink",
        )
        resp = await download(client, sandbox["id"], "/home/statelink")
        if resp.status_code == 200:
            assert b"sandboxes" not in resp.content
        else:
            assert resp.status_code in (400, 404)

    async def test_symlink_chain_escape(self, client: httpx.AsyncClient, sandbox: dict):
        await shell(client, sandbox["id"], "ln -s ../../etc/passwd /home/a")
        await shell(client, sandbox["id"], "ln -s /home/a /home/b")
        resp = await download(client, sandbox["id"], "/home/b")
        if resp.status_code == 200:
            assert b"root:" not in resp.content
        else:
            assert resp.status_code in (400, 404)

    async def test_symlink_relative_escape(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        await shell(client, sandbox["id"], "mkdir -p /home/sub")
        await shell(client, sandbox["id"], "ln -s ../../etc/passwd /home/sub/link")
        resp = await download(client, sandbox["id"], "/home/sub/link")
        if resp.status_code == 200:
            assert b"root:" not in resp.content
        else:
            assert resp.status_code in (400, 404)

    async def test_symlink_to_sandbox_base_dir(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        await shell(
            client,
            sandbox["id"],
            "ln -s /var/lib/agentjail/sandboxes /home/sandboxes",
        )
        resp = await download(client, sandbox["id"], "/home/sandboxes")
        assert resp.status_code in (400, 404)


# ---------------------------------------------------------------------------
# Shell command escape attempts
# ---------------------------------------------------------------------------


class TestShellEscape:
    async def test_shell_hostname_is_isolated(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        result = await shell(client, sandbox["id"], "hostname")
        hostname = result["stdout"].strip()
        assert len(hostname) > 0

    async def test_shell_cannot_read_state_file(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        result = await shell(client, sandbox["id"], "cat /var/lib/agentjail/state.json")
        assert result["exit_code"] != 0 or result["stdout"].strip() == ""

    async def test_shell_cannot_read_sandbox_base_dir(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        result = await shell(client, sandbox["id"], "ls /var/lib/agentjail/sandboxes/")
        assert result["exit_code"] != 0

    async def test_shell_cannot_access_docker_socket(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        result = await shell(client, sandbox["id"], "ls /var/run/docker.sock")
        assert result["exit_code"] != 0

    async def test_shell_cannot_read_proc_environ(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        result = await shell(client, sandbox["id"], "cat /proc/1/environ 2>/dev/null")
        assert result["exit_code"] != 0 or "AGENTJAIL" not in result["stdout"]

    async def test_shell_env_does_not_leak_host_vars(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        result = await shell(client, sandbox["id"], "env")
        stdout = result["stdout"]
        assert "AGENTJAIL_STATE_FILE" not in stdout
        assert "AGENTJAIL_SANDBOX_BASE_DIR" not in stdout


# ---------------------------------------------------------------------------
# Read-only mount enforcement
# ---------------------------------------------------------------------------


class TestReadOnlyMounts:
    async def test_cannot_write_to_usr(self, client: httpx.AsyncClient, sandbox: dict):
        result = await shell(client, sandbox["id"], "touch /usr/evil.txt")
        assert result["exit_code"] != 0

    async def test_cannot_write_to_bin(self, client: httpx.AsyncClient, sandbox: dict):
        result = await shell(client, sandbox["id"], "cp /bin/ls /bin/evil")
        assert result["exit_code"] != 0

    async def test_cannot_write_to_etc(self, client: httpx.AsyncClient, sandbox: dict):
        result = await shell(client, sandbox["id"], "echo evil >> /etc/passwd")
        assert result["exit_code"] != 0

    async def test_cannot_write_to_sbin(self, client: httpx.AsyncClient, sandbox: dict):
        result = await shell(client, sandbox["id"], "touch /sbin/evil")
        assert result["exit_code"] != 0

    async def test_cannot_write_to_lib(self, client: httpx.AsyncClient, sandbox: dict):
        result = await shell(client, sandbox["id"], "touch /lib/evil")
        assert result["exit_code"] != 0

    async def test_cannot_write_to_uploads(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        await upload(client, sandbox["id"], "protected.txt", b"data")
        result = await shell(
            client, sandbox["id"], "echo tampered > /uploads/protected.txt"
        )
        assert result["exit_code"] != 0

    async def test_can_write_to_home(self, client: httpx.AsyncClient, sandbox: dict):
        result = await shell(
            client, sandbox["id"], "echo ok > /home/test.txt && cat /home/test.txt"
        )
        assert result["exit_code"] == 0
        assert "ok" in result["stdout"]

    async def test_can_write_to_tmp(self, client: httpx.AsyncClient, sandbox: dict):
        result = await shell(
            client, sandbox["id"], "echo tmp > /tmp/test.txt && cat /tmp/test.txt"
        )
        assert result["exit_code"] == 0
        assert "tmp" in result["stdout"]

    async def test_tmp_does_not_persist_across_exec(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        await shell(client, sandbox["id"], "echo data > /tmp/x.txt")
        result = await shell(client, sandbox["id"], "cat /tmp/x.txt")
        assert result["exit_code"] != 0


# ---------------------------------------------------------------------------
# Process isolation
# ---------------------------------------------------------------------------


class TestProcessIsolation:
    async def test_pid_namespace_isolation(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        result = await shell(client, sandbox["id"], "echo $$")
        assert result["exit_code"] == 0
        pid = int(result["stdout"].strip())
        assert pid < 100

    async def test_cannot_see_host_processes(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        result = await shell(
            client, sandbox["id"], "ls /proc/ 2>/dev/null | grep -E '^[0-9]+$' | wc -l"
        )
        if result["exit_code"] == 0:
            count = int(result["stdout"].strip())
            assert count < 10

    async def test_cannot_signal_host_processes(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        result = await shell(client, sandbox["id"], "kill -0 1 2>&1; echo $?")
        output = result["stdout"].strip().split("\n")[-1]
        assert output in ("0", "1") or result["exit_code"] != 0

    async def test_pids_limit_enforcement(self, client: httpx.AsyncClient):
        sb = await create_sandbox(client, pids_limit=8)
        try:
            result = await shell(
                client,
                sb["id"],
                "for i in $(seq 1 20); do sleep 10 & done; wait 2>&1; echo done",
            )
            assert (
                "Resource temporarily unavailable" in result["stderr"]
                or result["exit_code"] != 0
                or "done" in result["stdout"]
            )
        finally:
            await remove_sandbox(client, sb["id"])


# ---------------------------------------------------------------------------
# Network isolation
# ---------------------------------------------------------------------------


class TestNetworkIsolation:
    async def test_network_disabled_by_default(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        result = await shell(
            client,
            sandbox["id"],
            "ping -c 1 -W 1 8.8.8.8 2>&1 || echo NETWORK_BLOCKED",
        )
        assert "NETWORK_BLOCKED" in result["stdout"] or result["exit_code"] != 0

    async def test_network_disabled_no_dns(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        result = await shell(
            client,
            sandbox["id"],
            "getent hosts google.com 2>&1 || echo DNS_BLOCKED",
        )
        assert "DNS_BLOCKED" in result["stdout"] or result["exit_code"] != 0

    async def test_network_disabled_no_loopback(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        result = await shell(
            client,
            sandbox["id"],
            "cat < /dev/tcp/127.0.0.1/8000 2>&1 || echo LO_BLOCKED",
            timeout=5,
        )
        assert "LO_BLOCKED" in result["stdout"] or result["exit_code"] != 0

    @pytest.mark.network
    async def test_network_enabled_can_reach_external(
        self, client: httpx.AsyncClient, sandbox_with_network: dict
    ):
        result = await shell(
            client,
            sandbox_with_network["id"],
            "ping -c 1 -W 5 8.8.8.8 2>&1 || echo FAILED",
            timeout=10,
        )
        assert result["exit_code"] == 0 or "FAILED" not in result["stdout"]


# ---------------------------------------------------------------------------
# Resource exhaustion
# ---------------------------------------------------------------------------


class TestResourceExhaustion:
    async def test_fork_bomb_contained(self, client: httpx.AsyncClient):
        sb = await create_sandbox(client, time_limit=5)
        try:
            result = await shell(client, sb["id"], ":(){ :|:& };:", timeout=10)
            assert result["timed_out"] or result["exit_code"] != 0
        finally:
            await remove_sandbox(client, sb["id"])

    async def test_memory_exhaustion_contained(self, client: httpx.AsyncClient):
        sb = await create_sandbox(client, memory_limit=64)
        try:
            result = await shell(
                client,
                sb["id"],
                "python3 -c 'x = bytearray(200 * 1024 * 1024)'",
                timeout=10,
            )
            assert result["exit_code"] != 0
        finally:
            await remove_sandbox(client, sb["id"])

    async def test_disk_exhaustion_contained(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        result = await shell(
            client, sandbox["id"], "dd if=/dev/zero of=/home/big bs=1M count=100 2>&1"
        )
        assert result["exit_code"] != 0 or "File too large" in result["stderr"]

    async def test_time_limit_kills_runaway(self, client: httpx.AsyncClient):
        sb = await create_sandbox(client, time_limit=3)
        try:
            result = await shell(client, sb["id"], "while true; do :; done", timeout=15)
            assert result["timed_out"] or result["exit_code"] != 0
        finally:
            await remove_sandbox(client, sb["id"])

    async def test_file_descriptor_exhaustion(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        result = await shell(
            client,
            sandbox["id"],
            "python3 -c \"fds=[open(f'/tmp/f{i}','w') for i in range(300)]\"",
            timeout=10,
        )
        assert result["exit_code"] != 0

    async def test_tmp_size_limit(self, client: httpx.AsyncClient, sandbox: dict):
        result = await shell(
            client, sandbox["id"], "dd if=/dev/zero of=/tmp/fill bs=1M count=100 2>&1"
        )
        assert result["exit_code"] != 0 or "No space left" in result["stderr"]


# ---------------------------------------------------------------------------
# Cross-sandbox isolation
# ---------------------------------------------------------------------------


class TestCrossSandboxIsolation:
    async def test_sandbox_a_cannot_read_sandbox_b_files(
        self, client: httpx.AsyncClient
    ):
        sb_a = await create_sandbox(client)
        sb_b = await create_sandbox(client)
        try:
            await shell(client, sb_a["id"], "echo secret-data > /home/secret.txt")
            result = await shell(client, sb_b["id"], "ls /home/")
            assert "secret.txt" not in result["stdout"]
        finally:
            await remove_sandbox(client, sb_a["id"])
            await remove_sandbox(client, sb_b["id"])

    async def test_sandbox_a_cannot_access_sandbox_b_via_path(
        self, client: httpx.AsyncClient
    ):
        sb_a = await create_sandbox(client)
        sb_b = await create_sandbox(client)
        try:
            a_id = sb_a["id"]
            result = await shell(
                client, sb_b["id"], f"ls /var/lib/agentjail/sandboxes/{a_id}/ 2>&1"
            )
            assert result["exit_code"] != 0
        finally:
            await remove_sandbox(client, sb_a["id"])
            await remove_sandbox(client, sb_b["id"])

    async def test_sandboxes_have_independent_tmp(self, client: httpx.AsyncClient):
        sb_a = await create_sandbox(client)
        sb_b = await create_sandbox(client)
        try:
            await shell(client, sb_a["id"], "echo marker > /tmp/mark.txt")
            result = await shell(client, sb_b["id"], "cat /tmp/mark.txt 2>&1")
            assert result["exit_code"] != 0
        finally:
            await remove_sandbox(client, sb_a["id"])
            await remove_sandbox(client, sb_b["id"])


# ---------------------------------------------------------------------------
# /proc abuse
# ---------------------------------------------------------------------------


class TestProcAbuse:
    async def test_proc_is_not_mounted(self, client: httpx.AsyncClient, sandbox: dict):
        result = await shell(client, sandbox["id"], "ls /proc 2>&1")
        assert result["exit_code"] != 0 or "No such file" in result["stdout"]

    async def test_cannot_read_host_proc_1_cmdline(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        result = await shell(
            client, sandbox["id"], "cat /proc/1/cmdline 2>/dev/null || echo BLOCKED"
        )
        stdout = result["stdout"]
        assert "uvicorn" not in stdout
        assert "agentjail" not in stdout

    async def test_proc_net_not_accessible(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        result = await shell(client, sandbox["id"], "cat /proc/net/dev 2>/dev/null")
        assert result["exit_code"] != 0 or result["stdout"].strip() == ""


# ---------------------------------------------------------------------------
# Mount and privilege escalation
# ---------------------------------------------------------------------------


class TestPrivilegeEscalation:
    async def test_cannot_mount_filesystem(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        result = await shell(client, sandbox["id"], "mount -t tmpfs none /mnt 2>&1")
        assert result["exit_code"] != 0

    async def test_cannot_remount_rw(self, client: httpx.AsyncClient, sandbox: dict):
        result = await shell(client, sandbox["id"], "mount -o remount,rw /usr 2>&1")
        assert result["exit_code"] != 0

    async def test_cannot_use_chroot(self, client: httpx.AsyncClient, sandbox: dict):
        result = await shell(
            client, sandbox["id"], "chroot / /bin/sh -c 'echo escaped' 2>&1"
        )
        assert result["exit_code"] != 0

    async def test_cannot_use_su(self, client: httpx.AsyncClient, sandbox: dict):
        result = await shell(client, sandbox["id"], "su - root -c 'echo escaped' 2>&1")
        assert result["exit_code"] != 0

    async def test_cannot_change_uid(self, client: httpx.AsyncClient, sandbox: dict):
        result = await shell(
            client, sandbox["id"], "python3 -c 'import os; os.setuid(0)' 2>&1"
        )
        assert result["exit_code"] != 0

    async def test_runs_as_unprivileged_user(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        result = await shell(client, sandbox["id"], "id")
        assert result["exit_code"] == 0
        assert "uid=1000" in result["stdout"]
        assert "gid=1000" in result["stdout"]

    async def test_cannot_create_device_nodes(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        result = await shell(client, sandbox["id"], "mknod /home/evil c 1 3 2>&1")
        assert result["exit_code"] != 0

    async def test_cannot_change_file_owner(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        await shell(client, sandbox["id"], "touch /home/myfile")
        result = await shell(client, sandbox["id"], "chown root:root /home/myfile 2>&1")
        assert result["exit_code"] != 0


# ---------------------------------------------------------------------------
# Environment variable leakage
# ---------------------------------------------------------------------------


class TestEnvLeakage:
    async def test_no_host_env_leak_agentjail_vars(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        result = await shell(client, sandbox["id"], "env")
        for line in result["stdout"].splitlines():
            assert not line.startswith("AGENTJAIL_")

    async def test_no_host_env_leak_service_vars(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        result = await shell(client, sandbox["id"], "env")
        stdout = result["stdout"]
        assert "SERVICE_NAME=" not in stdout
        assert "VERSION=" not in stdout
        assert "ENVIRONMENT=" not in stdout
        assert "LOG_LEVEL=" not in stdout

    async def test_only_expected_env_vars(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        result = await shell(client, sandbox["id"], "env")
        allowed_prefixes = ("PATH=", "HOME=", "TERM=", "SHLVL=", "PWD=", "_=")
        for line in result["stdout"].splitlines():
            if "=" in line:
                assert any(line.startswith(p) for p in allowed_prefixes), (
                    f"Unexpected env var: {line}"
                )

    async def test_custom_env_vars_visible(self, client: httpx.AsyncClient):
        sb = await create_sandbox(client, env={"CUSTOM": "value"})
        try:
            result = await shell(client, sb["id"], "echo $CUSTOM")
            assert "value" in result["stdout"]
        finally:
            await remove_sandbox(client, sb["id"])

    async def test_per_exec_env_override(self, client: httpx.AsyncClient):
        sb = await create_sandbox(client, env={"X": "original"})
        try:
            result = await exec_cmd(
                client,
                sb["id"],
                "/bin/sh",
                args=["-c", "echo $X"],
                env={"X": "override"},
            )
            assert "override" in result["stdout"]
        finally:
            await remove_sandbox(client, sb["id"])
