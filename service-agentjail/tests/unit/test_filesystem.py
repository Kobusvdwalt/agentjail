import httpx

from helpers import download, fetch_hosted, sandbox_host_file, upload


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


class TestSandboxHostFile:
    async def test_host_file_creates_url(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        await upload(client, sandbox["id"], "report.csv", b"a,b,c")
        resp = await sandbox_host_file(client, sandbox["id"], "/uploads/report.csv")
        assert resp.status_code == 200
        data = resp.json()
        assert data["filename"] == "report.csv"
        assert data["size"] == 5
        assert data["download_url"].startswith(
            f"/api/v1/sandbox/{sandbox['id']}/hosted/"
        )
        assert data["download_url"].endswith(".csv")

    async def test_hosted_file_is_fetchable(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        content = b"hello world"
        await upload(client, sandbox["id"], "data.txt", content)
        resp = await sandbox_host_file(client, sandbox["id"], "/uploads/data.txt")
        data = resp.json()
        filename = data["download_url"].rsplit("/", 1)[-1]
        fetch_resp = await fetch_hosted(client, sandbox["id"], filename)
        assert fetch_resp.status_code == 200
        assert fetch_resp.content == content

    async def test_host_file_binary_roundtrip(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        content = bytes(range(256))
        await upload(client, sandbox["id"], "binary.bin", content)
        resp = await sandbox_host_file(client, sandbox["id"], "/uploads/binary.bin")
        data = resp.json()
        filename = data["download_url"].rsplit("/", 1)[-1]
        fetch_resp = await fetch_hosted(client, sandbox["id"], filename)
        assert fetch_resp.content == content

    async def test_host_file_nonexistent_file(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        resp = await sandbox_host_file(client, sandbox["id"], "/uploads/nope.txt")
        assert resp.status_code == 404

    async def test_fetch_nonexistent_hosted_file(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        resp = await fetch_hosted(client, sandbox["id"], "nonexistent.txt")
        assert resp.status_code == 404

    async def test_host_file_nonexistent_sandbox(self, client: httpx.AsyncClient):
        resp = await sandbox_host_file(client, "nonexistent-uuid", "/home/file.txt")
        assert resp.status_code == 404

    async def test_legacy_download_route_removed(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        resp = await client.post(
            f"/sandbox/{sandbox['id']}/download", params={"path": "/uploads/file.txt"}
        )
        assert resp.status_code == 404

    async def test_legacy_download_fetch_route_removed(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        resp = await client.get(f"/sandbox/{sandbox['id']}/downloads/file.txt")
        assert resp.status_code == 404


class TestNonexistentSandbox:
    async def test_upload_nonexistent_sandbox(self, client: httpx.AsyncClient):
        fake_id = "nonexistent-uuid"
        resp = await upload(client, fake_id, "test.txt", b"data")
        assert resp.status_code == 404

    async def test_download_nonexistent_sandbox(self, client: httpx.AsyncClient):
        fake_id = "nonexistent-uuid"
        resp = await download(client, fake_id, "/uploads/test.txt")
        assert resp.status_code == 404
