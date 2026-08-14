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

    async def test_symlink_download_sandbox_metadata(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        """Metadata is not reachable through the filesystem API.

        It carries `config.env`, which is where a caller puts the credential the
        sandbox acts with — so it is kept in a sibling directory rather than
        under the sandbox root that downloads resolve against, and a symlink
        pointing back at it escapes that root like any other.
        """
        root_dir = sandbox["root_dir"]
        meta_path = os.path.join(
            os.path.dirname(os.path.dirname(root_dir)),
            "meta",
            f"{sandbox['id']}.json",
        )
        assert os.path.exists(meta_path), "metadata should live outside the root"

        os.symlink(meta_path, os.path.join(root_dir, "uploads", "metalink"))
        resp = await download(client, sandbox["id"], "/uploads/metalink")
        if resp.status_code == 200:
            assert b'"env"' not in resp.content
        else:
            assert resp.status_code in (400, 404)

    async def test_download_cannot_reach_metadata_directly(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        """The direct form of the above, without a symlink to help it."""
        for path in ("/meta.json", f"../meta/{sandbox['id']}.json"):
            resp = await download(client, sandbox["id"], path)
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
