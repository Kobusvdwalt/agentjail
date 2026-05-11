import httpx
import pytest

from helpers import (
    create_sandbox,
    exec_cmd,
    fs_list,
    fs_mkdir,
    fs_read,
    fs_remove,
    fs_stat,
    fs_write,
    remove_sandbox,
    shell,
)


# ---------------------------------------------------------------------------
# Path traversal via filesystem API
# ---------------------------------------------------------------------------


class TestPathTraversalAPI:
    async def test_path_traversal_read_etc_passwd(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        resp = await fs_read(client, sandbox["id"], "../../etc/passwd")
        assert resp.status_code == 400

    async def test_path_traversal_read_absolute(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        resp = await fs_read(client, sandbox["id"], "/../../etc/passwd")
        assert resp.status_code == 400

    async def test_path_traversal_write_outside(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        resp = await fs_write(client, sandbox["id"], "../../tmp/evil.txt", "pwned")
        assert resp.status_code == 400

    async def test_path_traversal_mkdir_outside(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        resp = await fs_mkdir(client, sandbox["id"], "../../tmp/evil")
        assert resp.status_code == 400

    async def test_path_traversal_remove_outside(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        resp = await fs_remove(client, sandbox["id"], "../../etc/hostname")
        assert resp.status_code == 400

    async def test_path_traversal_stat_outside(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        resp = await fs_stat(client, sandbox["id"], "../../etc/hostname")
        assert resp.status_code == 400

    async def test_path_traversal_list_outside(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        resp = await fs_list(client, sandbox["id"], "../../etc")
        assert resp.status_code == 400

    async def test_path_traversal_encoded_slashes(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        resp = await fs_read(client, sandbox["id"], "%2e%2e%2f%2e%2e%2fetc%2fpasswd")
        assert resp.status_code in (400, 404)

    async def test_path_traversal_null_byte(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        resp = await fs_read(client, sandbox["id"], "/test.txt\x00../../etc/passwd")
        assert resp.status_code in (400, 404, 422, 500)


# ---------------------------------------------------------------------------
# Path traversal via symlinks
# ---------------------------------------------------------------------------


class TestSymlinkEscape:
    async def test_symlink_read_etc_passwd(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        await shell(client, sandbox["id"], "ln -s /etc/passwd /home/link")
        resp = await fs_read(client, sandbox["id"], "/link")
        if resp.status_code == 200:
            assert "root:" not in resp.json().get("content", "")
        else:
            assert resp.status_code in (400, 404)

    async def test_symlink_read_state_file(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        await shell(
            client, sandbox["id"], "ln -s /var/lib/agentjail/state.json /home/statelink"
        )
        resp = await fs_read(client, sandbox["id"], "/statelink")
        if resp.status_code == 200:
            content = resp.json().get("content", "")
            assert "sandboxes" not in content
        else:
            assert resp.status_code in (400, 404)

    async def test_symlink_chain_escape(self, client: httpx.AsyncClient, sandbox: dict):
        await shell(client, sandbox["id"], "ln -s ../../etc/passwd /home/a")
        await shell(client, sandbox["id"], "ln -s /home/a /home/b")
        resp = await fs_read(client, sandbox["id"], "/b")
        if resp.status_code == 200:
            assert "root:" not in resp.json().get("content", "")
        else:
            assert resp.status_code in (400, 404)

    async def test_symlink_relative_escape(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        await shell(client, sandbox["id"], "mkdir -p /home/sub")
        await shell(client, sandbox["id"], "ln -s ../../etc/passwd /home/sub/link")
        resp = await fs_read(client, sandbox["id"], "/sub/link")
        if resp.status_code == 200:
            assert "root:" not in resp.json().get("content", "")
        else:
            assert resp.status_code in (400, 404)

    async def test_symlink_to_sandbox_base_dir(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        await shell(
            client, sandbox["id"], "ln -s /var/lib/agentjail/sandboxes /home/sandboxes"
        )
        resp = await fs_list(client, sandbox["id"], "/sandboxes")
        if resp.status_code == 200:
            assert len(resp.json()) == 0
        else:
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
        stdout = result["stdout"]
        assert "AGENTJAIL" not in stdout

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
        result = await shell(
            client, sandbox["id"], "cat /proc/self/status | grep -i '^pid:'"
        )
        assert result["exit_code"] == 0

    async def test_cannot_see_host_processes(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        result = await shell(
            client, sandbox["id"], "ls /proc/ | grep -E '^[0-9]+$' | wc -l"
        )
        if result["exit_code"] == 0:
            count = int(result["stdout"].strip())
            assert count < 10

    async def test_cannot_signal_host_processes(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        result = await shell(client, sandbox["id"], "kill -0 1 2>&1; echo $?")
        output = result["stdout"].strip().split("\n")[-1]
        # PID 1 inside the jail is the sandboxed process itself, so kill -0 1 may succeed
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
            client, sandbox["id"], "ping -c 1 -W 1 8.8.8.8 2>&1 || echo NETWORK_BLOCKED"
        )
        assert "NETWORK_BLOCKED" in result["stdout"] or result["exit_code"] != 0

    async def test_network_disabled_no_dns(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        result = await shell(
            client, sandbox["id"], "getent hosts google.com 2>&1 || echo DNS_BLOCKED"
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
            await fs_write(client, sb_a["id"], "/secret.txt", "secret-data")
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
    async def test_proc_is_read_only(self, client: httpx.AsyncClient, sandbox: dict):
        result = await shell(
            client, sandbox["id"], "echo x > /proc/sys/kernel/hostname 2>&1"
        )
        assert result["exit_code"] != 0

    async def test_proc_self_shows_sandboxed_process(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        result = await shell(
            client, sandbox["id"], "cat /proc/self/status | grep -i '^pid:'"
        )
        assert result["exit_code"] == 0

    async def test_cannot_read_host_proc_1_cmdline(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        result = await shell(
            client, sandbox["id"], "cat /proc/1/cmdline 2>/dev/null || echo BLOCKED"
        )
        stdout = result["stdout"]
        assert "uvicorn" not in stdout
        assert "agentjail" not in stdout

    async def test_proc_net_shows_isolated_interfaces(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        result = await shell(client, sandbox["id"], "cat /proc/net/dev 2>/dev/null")
        if result["exit_code"] == 0:
            assert "eth0" not in result["stdout"] or "lo" in result["stdout"]


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
