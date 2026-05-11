import httpx

from helpers import download, shell, upload


class TestUpload:
    async def test_upload_file(self, client: httpx.AsyncClient, sandbox: dict):
        resp = await upload(client, sandbox["id"], "test.txt", b"hello")
        assert resp.status_code == 200
        assert resp.json()["path"] == "/uploads/test.txt"

    async def test_upload_binary(self, client: httpx.AsyncClient, sandbox: dict):
        data = bytes(range(256))
        resp = await upload(client, sandbox["id"], "binary.bin", data)
        assert resp.status_code == 200

    async def test_upload_unicode_content(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        content = "Hello 世界 🌍 éàüñ".encode()
        resp = await upload(client, sandbox["id"], "unicode.txt", content)
        assert resp.status_code == 200

    async def test_upload_large_file(self, client: httpx.AsyncClient, sandbox: dict):
        content = b"A" * (1024 * 1024)
        resp = await upload(client, sandbox["id"], "large.bin", content)
        assert resp.status_code == 200

    async def test_upload_overwrites(self, client: httpx.AsyncClient, sandbox: dict):
        await upload(client, sandbox["id"], "file.txt", b"first")
        await upload(client, sandbox["id"], "file.txt", b"second")
        resp = await download(client, sandbox["id"], "/uploads/file.txt")
        assert resp.content == b"second"


class TestUploadVisibleInShell:
    async def test_uploaded_file_readable_via_shell(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        await upload(client, sandbox["id"], "plan.md", b"# My Plan")
        result = await shell(client, sandbox["id"], "cat /uploads/plan.md")
        assert result["exit_code"] == 0
        assert "# My Plan" in result["stdout"]

    async def test_uploaded_binary_readable_via_shell(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        await upload(client, sandbox["id"], "data.bin", b"\x00\x01\x02\x03")
        result = await shell(client, sandbox["id"], "wc -c < /uploads/data.bin")
        assert result["exit_code"] == 0
        assert result["stdout"].strip() == "4"

    async def test_uploads_dir_listed_via_shell(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        await upload(client, sandbox["id"], "a.txt", b"a")
        await upload(client, sandbox["id"], "b.txt", b"b")
        result = await shell(client, sandbox["id"], "ls /uploads/")
        assert result["exit_code"] == 0
        assert "a.txt" in result["stdout"]
        assert "b.txt" in result["stdout"]

    async def test_uploads_readonly_via_shell(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        await upload(client, sandbox["id"], "readonly.txt", b"data")
        result = await shell(
            client, sandbox["id"], "echo tampered > /uploads/readonly.txt"
        )
        assert result["exit_code"] != 0


class TestDownload:
    async def test_download_uploaded_file(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        await upload(client, sandbox["id"], "dl.txt", b"download me")
        resp = await download(client, sandbox["id"], "/uploads/dl.txt")
        assert resp.status_code == 200
        assert resp.content == b"download me"

    async def test_download_binary_roundtrip(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        data = bytes(range(256))
        await upload(client, sandbox["id"], "roundtrip.bin", data)
        resp = await download(client, sandbox["id"], "/uploads/roundtrip.bin")
        assert resp.content == data

    async def test_download_nonexistent(self, client: httpx.AsyncClient, sandbox: dict):
        resp = await download(client, sandbox["id"], "/uploads/no-such-file")
        assert resp.status_code == 404

    async def test_download_from_home(self, client: httpx.AsyncClient, sandbox: dict):
        await shell(client, sandbox["id"], "echo -n hello > /home/output.txt")
        resp = await download(client, sandbox["id"], "/home/output.txt")
        assert resp.status_code == 200
        assert resp.content == b"hello"


class TestNonexistentSandbox:
    async def test_upload_nonexistent_sandbox(self, client: httpx.AsyncClient):
        fake_id = "nonexistent-uuid"
        resp = await upload(client, fake_id, "test.txt", b"data")
        assert resp.status_code == 404

    async def test_download_nonexistent_sandbox(self, client: httpx.AsyncClient):
        fake_id = "nonexistent-uuid"
        resp = await download(client, fake_id, "/uploads/test.txt")
        assert resp.status_code == 404
