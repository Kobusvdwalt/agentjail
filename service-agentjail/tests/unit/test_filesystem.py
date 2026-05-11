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


class TestWriteAndRead:
    async def test_fs_write_and_read(self, client: httpx.AsyncClient, sandbox: dict):
        resp = await fs_write(client, sandbox["id"], "/test.txt", "hello")
        assert resp.status_code == 200

        resp = await fs_read(client, sandbox["id"], "/test.txt")
        assert resp.status_code == 200
        assert resp.json()["content"] == "hello"

    async def test_fs_write_creates_parent_dirs(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        resp = await fs_write(client, sandbox["id"], "/a/b/c/deep.txt", "nested")
        assert resp.status_code == 200

        resp = await fs_read(client, sandbox["id"], "/a/b/c/deep.txt")
        assert resp.status_code == 200
        assert resp.json()["content"] == "nested"

    async def test_fs_write_overwrite(self, client: httpx.AsyncClient, sandbox: dict):
        await fs_write(client, sandbox["id"], "/file.txt", "first")
        await fs_write(client, sandbox["id"], "/file.txt", "second")

        resp = await fs_read(client, sandbox["id"], "/file.txt")
        assert resp.json()["content"] == "second"

    async def test_fs_read_nonexistent(self, client: httpx.AsyncClient, sandbox: dict):
        resp = await fs_read(client, sandbox["id"], "/no-such-file")
        assert resp.status_code == 404

    async def test_fs_write_unicode(self, client: httpx.AsyncClient, sandbox: dict):
        content = "Hello 世界 🌍 éàüñ"
        await fs_write(client, sandbox["id"], "/unicode.txt", content)
        resp = await fs_read(client, sandbox["id"], "/unicode.txt")
        assert resp.json()["content"] == content

    async def test_fs_write_large_file(self, client: httpx.AsyncClient, sandbox: dict):
        content = "A" * (1024 * 1024)
        await fs_write(client, sandbox["id"], "/large.txt", content)
        resp = await fs_read(client, sandbox["id"], "/large.txt")
        assert resp.json()["content"] == content


class TestMkdir:
    async def test_fs_mkdir(self, client: httpx.AsyncClient, sandbox: dict):
        resp = await fs_mkdir(client, sandbox["id"], "/mydir")
        assert resp.status_code == 200

        resp = await fs_list(client, sandbox["id"], "/mydir")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_fs_mkdir_nested(self, client: httpx.AsyncClient, sandbox: dict):
        resp = await fs_mkdir(client, sandbox["id"], "/a/b/c")
        assert resp.status_code == 200

        resp = await fs_stat(client, sandbox["id"], "/a/b/c")
        assert resp.status_code == 200
        assert resp.json()["kind"] == "directory"

    async def test_fs_mkdir_idempotent(self, client: httpx.AsyncClient, sandbox: dict):
        await fs_mkdir(client, sandbox["id"], "/mydir")
        resp = await fs_mkdir(client, sandbox["id"], "/mydir")
        assert resp.status_code == 200


class TestList:
    async def test_fs_list_root(self, client: httpx.AsyncClient, sandbox: dict):
        await fs_write(client, sandbox["id"], "/file.txt", "data")
        await fs_mkdir(client, sandbox["id"], "/subdir")

        resp = await fs_list(client, sandbox["id"], "/")
        assert resp.status_code == 200
        names = [e["name"] for e in resp.json()]
        assert "file.txt" in names
        assert "subdir" in names

    async def test_fs_list_entries_have_correct_fields(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        await fs_write(client, sandbox["id"], "/check.txt", "data")

        resp = await fs_list(client, sandbox["id"], "/")
        entries = resp.json()
        entry = next(e for e in entries if e["name"] == "check.txt")
        assert "name" in entry
        assert "path" in entry
        assert "kind" in entry
        assert "size" in entry
        assert "mode" in entry
        assert "modified" in entry

    async def test_fs_list_nonexistent_dir(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        resp = await fs_list(client, sandbox["id"], "/no-such-dir")
        assert resp.status_code == 404

    async def test_fs_list_many_entries(self, client: httpx.AsyncClient, sandbox: dict):
        for i in range(20):
            await fs_write(client, sandbox["id"], f"/batch/file_{i}.txt", f"data_{i}")

        resp = await fs_list(client, sandbox["id"], "/batch")
        assert len(resp.json()) == 20


class TestStat:
    async def test_fs_stat_file(self, client: httpx.AsyncClient, sandbox: dict):
        await fs_write(client, sandbox["id"], "/stat-test.txt", "data")
        resp = await fs_stat(client, sandbox["id"], "/stat-test.txt")
        assert resp.status_code == 200
        data = resp.json()
        assert data["kind"] == "file"
        assert data["size"] == 4

    async def test_fs_stat_directory(self, client: httpx.AsyncClient, sandbox: dict):
        await fs_mkdir(client, sandbox["id"], "/stat-dir")
        resp = await fs_stat(client, sandbox["id"], "/stat-dir")
        assert resp.status_code == 200
        assert resp.json()["kind"] == "directory"

    async def test_fs_stat_nonexistent(self, client: httpx.AsyncClient, sandbox: dict):
        resp = await fs_stat(client, sandbox["id"], "/ghost")
        assert resp.status_code == 404


class TestRemove:
    async def test_fs_remove_file(self, client: httpx.AsyncClient, sandbox: dict):
        await fs_write(client, sandbox["id"], "/removeme.txt", "gone")
        resp = await fs_remove(client, sandbox["id"], "/removeme.txt")
        assert resp.status_code == 200

        resp = await fs_read(client, sandbox["id"], "/removeme.txt")
        assert resp.status_code == 404

    async def test_fs_remove_directory(self, client: httpx.AsyncClient, sandbox: dict):
        await fs_mkdir(client, sandbox["id"], "/removedir")
        await fs_write(client, sandbox["id"], "/removedir/file.txt", "data")
        resp = await fs_remove(client, sandbox["id"], "/removedir")
        assert resp.status_code == 200

        resp = await fs_list(client, sandbox["id"], "/removedir")
        assert resp.status_code == 404

    async def test_fs_remove_nonexistent(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        resp = await fs_remove(client, sandbox["id"], "/nope")
        assert resp.status_code == 404


class TestNonexistentSandbox:
    async def test_fs_operations_on_nonexistent_sandbox(
        self, client: httpx.AsyncClient
    ):
        fake_id = "nonexistent-uuid"
        assert (await fs_read(client, fake_id, "/x")).status_code == 404
        assert (await fs_write(client, fake_id, "/x", "y")).status_code == 404
        assert (await fs_list(client, fake_id, "/")).status_code == 404
        assert (await fs_mkdir(client, fake_id, "/x")).status_code == 404
        assert (await fs_remove(client, fake_id, "/x")).status_code == 404
        assert (await fs_stat(client, fake_id, "/x")).status_code == 404


class TestSymlink:
    async def test_fs_stat_symlink(self, client: httpx.AsyncClient, sandbox: dict):
        root_dir = sandbox["root_dir"]
        await fs_write(client, sandbox["id"], "/target.txt", "data")
        os.symlink("target.txt", os.path.join(root_dir, "link.txt"))
        resp = await fs_stat(client, sandbox["id"], "/link.txt")
        assert resp.status_code == 200
