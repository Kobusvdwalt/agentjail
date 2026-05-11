import os

import httpx

from helpers import (
    fs_list,
    fs_mkdir,
    fs_read,
    fs_remove,
    fs_stat,
    fs_write,
)


class TestPathTraversalAPI:
    async def test_path_traversal_read_etc_passwd(self, client: httpx.AsyncClient, sandbox: dict):
        resp = await fs_read(client, sandbox["id"], "../../etc/passwd")
        assert resp.status_code == 400

    async def test_path_traversal_read_absolute(self, client: httpx.AsyncClient, sandbox: dict):
        resp = await fs_read(client, sandbox["id"], "/../../etc/passwd")
        assert resp.status_code == 400

    async def test_path_traversal_write_outside(self, client: httpx.AsyncClient, sandbox: dict):
        resp = await fs_write(client, sandbox["id"], "../../tmp/evil.txt", "pwned")
        assert resp.status_code == 400

    async def test_path_traversal_mkdir_outside(self, client: httpx.AsyncClient, sandbox: dict):
        resp = await fs_mkdir(client, sandbox["id"], "../../tmp/evil")
        assert resp.status_code == 400

    async def test_path_traversal_remove_outside(self, client: httpx.AsyncClient, sandbox: dict):
        resp = await fs_remove(client, sandbox["id"], "../../etc/hostname")
        assert resp.status_code == 400

    async def test_path_traversal_stat_outside(self, client: httpx.AsyncClient, sandbox: dict):
        resp = await fs_stat(client, sandbox["id"], "../../etc/hostname")
        assert resp.status_code == 400

    async def test_path_traversal_list_outside(self, client: httpx.AsyncClient, sandbox: dict):
        resp = await fs_list(client, sandbox["id"], "../../etc")
        assert resp.status_code == 400

    async def test_path_traversal_encoded_slashes(self, client: httpx.AsyncClient, sandbox: dict):
        resp = await fs_read(client, sandbox["id"], "%2e%2e%2f%2e%2e%2fetc%2fpasswd")
        assert resp.status_code in (400, 404)

    async def test_path_traversal_null_byte(self, client: httpx.AsyncClient, sandbox: dict):
        try:
            resp = await fs_read(client, sandbox["id"], "/test.txt\x00../../etc/passwd")
            assert resp.status_code in (400, 404, 422, 500)
        except ValueError:
            pass


class TestSymlinkEscape:
    async def test_symlink_read_etc_passwd(self, client: httpx.AsyncClient, sandbox: dict):
        root_dir = sandbox["root_dir"]
        os.symlink("/etc/passwd", os.path.join(root_dir, "link"))
        resp = await fs_read(client, sandbox["id"], "/link")
        if resp.status_code == 200:
            assert "root:" not in resp.json().get("content", "")
        else:
            assert resp.status_code in (400, 404)

    async def test_symlink_read_state_file(self, client: httpx.AsyncClient, sandbox: dict):
        root_dir = sandbox["root_dir"]
        os.symlink("/var/lib/agentjail/state.json", os.path.join(root_dir, "statelink"))
        resp = await fs_read(client, sandbox["id"], "/statelink")
        if resp.status_code == 200:
            content = resp.json().get("content", "")
            assert "sandboxes" not in content
        else:
            assert resp.status_code in (400, 404)

    async def test_symlink_chain_escape(self, client: httpx.AsyncClient, sandbox: dict):
        root_dir = sandbox["root_dir"]
        os.symlink("../../etc/passwd", os.path.join(root_dir, "a"))
        os.symlink("a", os.path.join(root_dir, "b"))
        resp = await fs_read(client, sandbox["id"], "/b")
        if resp.status_code == 200:
            assert "root:" not in resp.json().get("content", "")
        else:
            assert resp.status_code in (400, 404)

    async def test_symlink_relative_escape(self, client: httpx.AsyncClient, sandbox: dict):
        root_dir = sandbox["root_dir"]
        os.makedirs(os.path.join(root_dir, "sub"), exist_ok=True)
        os.symlink("../../etc/passwd", os.path.join(root_dir, "sub", "link"))
        resp = await fs_read(client, sandbox["id"], "/sub/link")
        if resp.status_code == 200:
            assert "root:" not in resp.json().get("content", "")
        else:
            assert resp.status_code in (400, 404)

    async def test_symlink_to_sandbox_base_dir(self, client: httpx.AsyncClient, sandbox: dict):
        root_dir = sandbox["root_dir"]
        os.symlink("/var/lib/agentjail/sandboxes", os.path.join(root_dir, "sandboxes"))
        resp = await fs_list(client, sandbox["id"], "/sandboxes")
        if resp.status_code == 200:
            assert len(resp.json()) == 0
        else:
            assert resp.status_code in (400, 404)
