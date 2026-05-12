import httpx

from helpers import create_sandbox, remove_sandbox, shell


class TestResources:
    async def test_resources_readable(self, client: httpx.AsyncClient, sandbox: dict):
        result = await shell(client, sandbox["id"], "cat /resources/hello.txt")
        assert result["exit_code"] == 0
        assert "hello from resources" in result["stdout"]

    async def test_resources_nested_file(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        result = await shell(client, sandbox["id"], "cat /resources/subdir/nested.txt")
        assert result["exit_code"] == 0
        assert "nested file" in result["stdout"]

    async def test_resources_ls(self, client: httpx.AsyncClient, sandbox: dict):
        result = await shell(client, sandbox["id"], "ls /resources")
        assert result["exit_code"] == 0
        assert "hello.txt" in result["stdout"]
        assert "subdir" in result["stdout"]

    async def test_resources_not_writable(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        result = await shell(
            client, sandbox["id"], "echo hacked > /resources/hello.txt"
        )
        assert result["exit_code"] != 0

    async def test_resources_cannot_create_file(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        result = await shell(client, sandbox["id"], "touch /resources/newfile.txt")
        assert result["exit_code"] != 0

    async def test_resources_cannot_delete_file(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        result = await shell(client, sandbox["id"], "rm /resources/hello.txt")
        assert result["exit_code"] != 0

    async def test_resources_shared_across_sandboxes(self, client: httpx.AsyncClient):
        sb1 = await create_sandbox(client)
        sb2 = await create_sandbox(client)
        try:
            r1 = await shell(client, sb1["id"], "cat /resources/hello.txt")
            r2 = await shell(client, sb2["id"], "cat /resources/hello.txt")
            assert r1["stdout"] == r2["stdout"]
            assert "hello from resources" in r1["stdout"]
        finally:
            await remove_sandbox(client, sb1["id"])
            await remove_sandbox(client, sb2["id"])

    async def test_resources_skill_md_readable(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        result = await shell(
            client, sandbox["id"], "cat /resources/pdf-extractor/SKILL.md"
        )
        assert result["exit_code"] == 0
        assert "pdf-extractor" in result["stdout"]
        assert "Extract text from PDFs" in result["stdout"]

    async def test_resources_skill_discoverable_via_find(
        self, client: httpx.AsyncClient, sandbox: dict
    ):
        result = await shell(client, sandbox["id"], "find /resources -name SKILL.md")
        assert result["exit_code"] == 0
        assert "/resources/pdf-extractor/SKILL.md" in result["stdout"]
