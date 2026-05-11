import os

import httpx

from helpers import download


class TestPathTraversalDownload:
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
        try:
            resp = await download(
                client, sandbox["id"], "/test.txt\x00../../etc/passwd"
            )
            assert resp.status_code in (400, 404, 422, 500)
        except ValueError:
            pass


class TestSymlinkEscape:
    async def test_symlink_download_etc_passwd(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        root_dir = sandbox["root_dir"]
        os.symlink("/etc/passwd", os.path.join(root_dir, "uploads", "link"))
        resp = await download(client, sandbox["id"], "/uploads/link")
        if resp.status_code == 200:
            assert b"root:" not in resp.content
        else:
            assert resp.status_code in (400, 404)

    async def test_symlink_download_state_file(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        root_dir = sandbox["root_dir"]
        os.symlink(
            "/var/lib/agentjail/state.json",
            os.path.join(root_dir, "uploads", "statelink"),
        )
        resp = await download(client, sandbox["id"], "/uploads/statelink")
        if resp.status_code == 200:
            assert b"sandboxes" not in resp.content
        else:
            assert resp.status_code in (400, 404)

    async def test_symlink_chain_escape(self, client: httpx.AsyncClient, sandbox: dict):
        root_dir = sandbox["root_dir"]
        os.symlink("../../etc/passwd", os.path.join(root_dir, "uploads", "a"))
        os.symlink("a", os.path.join(root_dir, "uploads", "b"))
        resp = await download(client, sandbox["id"], "/uploads/b")
        if resp.status_code == 200:
            assert b"root:" not in resp.content
        else:
            assert resp.status_code in (400, 404)

    async def test_symlink_relative_escape(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        root_dir = sandbox["root_dir"]
        sub = os.path.join(root_dir, "uploads", "sub")
        os.makedirs(sub, exist_ok=True)
        os.symlink("../../../etc/passwd", os.path.join(sub, "link"))
        resp = await download(client, sandbox["id"], "/uploads/sub/link")
        if resp.status_code == 200:
            assert b"root:" not in resp.content
        else:
            assert resp.status_code in (400, 404)
