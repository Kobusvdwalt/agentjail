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


class TestResourcePatterns:
    """Selecting resources per sandbox, enforced by the mount rather than by
    the listing — so the check that matters is whether an excluded file can be
    read from inside a real jail."""

    async def test_selected_subset_is_readable(self, client: httpx.AsyncClient):
        sandbox = await create_sandbox(client, resources=["subdir/**"])
        try:
            result = await shell(
                client, sandbox["id"], "cat /resources/subdir/nested.txt"
            )
            assert result["exit_code"] == 0
            assert "nested file" in result["stdout"]
        finally:
            await remove_sandbox(client, sandbox["id"])

    async def test_excluded_file_cannot_be_read(self, client: httpx.AsyncClient):
        sandbox = await create_sandbox(client, resources=["subdir/**"])
        try:
            result = await shell(client, sandbox["id"], "cat /resources/hello.txt")
            assert result["exit_code"] != 0
            assert "hello from resources" not in result["stdout"]
        finally:
            await remove_sandbox(client, sandbox["id"])

    async def test_excluded_directory_is_not_listed(self, client: httpx.AsyncClient):
        sandbox = await create_sandbox(client, resources=["subdir/**"])
        try:
            result = await shell(client, sandbox["id"], "ls /resources")
            assert "subdir" in result["stdout"]
            assert "pdf-extractor" not in result["stdout"]
            assert "hello.txt" not in result["stdout"]
        finally:
            await remove_sandbox(client, sandbox["id"])

    async def test_star_still_sees_everything(self, client: httpx.AsyncClient):
        sandbox = await create_sandbox(client, resources=["*"])
        try:
            result = await shell(client, sandbox["id"], "ls /resources")
            assert "hello.txt" in result["stdout"]
            assert "subdir" in result["stdout"]
        finally:
            await remove_sandbox(client, sandbox["id"])

    async def test_two_sandboxes_see_different_resources(
        self, client: httpx.AsyncClient
    ):
        # The reason this feature exists: one agent's resources hidden from
        # another's, on the same shared directory.
        assistant = await create_sandbox(client, resources=["pdf-extractor/**"])
        protocols = await create_sandbox(client, resources=["subdir/**"])
        try:
            seen_by_assistant = await shell(client, assistant["id"], "ls /resources")
            seen_by_protocols = await shell(client, protocols["id"], "ls /resources")

            assert "pdf-extractor" in seen_by_assistant["stdout"]
            assert "subdir" not in seen_by_assistant["stdout"]

            assert "subdir" in seen_by_protocols["stdout"]
            assert "pdf-extractor" not in seen_by_protocols["stdout"]
        finally:
            await remove_sandbox(client, assistant["id"])
            await remove_sandbox(client, protocols["id"])

    async def test_no_resources_leaves_the_mount_empty(self, client: httpx.AsyncClient):
        sandbox = await create_sandbox(client, resources=[])
        try:
            result = await shell(client, sandbox["id"], "ls /resources")
            # Nothing mounted, so the directory is absent or empty — either way
            # no resource file is reachable.
            assert "hello.txt" not in result["stdout"]
            assert "pdf-extractor" not in result["stdout"]
        finally:
            await remove_sandbox(client, sandbox["id"])
