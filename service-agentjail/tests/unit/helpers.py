import httpx


async def create_sandbox(client: httpx.AsyncClient, **overrides) -> dict:
    resp = await client.post("/sandbox", json=overrides)
    assert resp.status_code == 200
    return resp.json()


async def remove_sandbox(
    client: httpx.AsyncClient, sandbox_id: str, force: bool = True
):
    await client.delete(f"/sandbox/{sandbox_id}", params={"force": True})


async def shell(
    client: httpx.AsyncClient, sandbox_id: str, command: str, timeout: int | None = None
) -> dict:
    body: dict = {"command": command}
    if timeout is not None:
        body["timeout"] = timeout
    resp = await client.post(f"/sandbox/{sandbox_id}/shell", json=body)
    assert resp.status_code == 200
    return resp.json()


async def upload(
    client: httpx.AsyncClient,
    sandbox_id: str,
    filename: str,
    content: bytes,
    content_type: str = "application/octet-stream",
) -> httpx.Response:
    return await client.post(
        f"/sandbox/{sandbox_id}/fs/upload",
        files={"file": (filename, content, content_type)},
    )


async def download(
    client: httpx.AsyncClient, sandbox_id: str, path: str
) -> httpx.Response:
    return await client.get(f"/sandbox/{sandbox_id}/fs/download", params={"path": path})


async def sandbox_host_file(
    client: httpx.AsyncClient, sandbox_id: str, path: str
) -> httpx.Response:
    return await client.post(f"/sandbox/{sandbox_id}/host", params={"path": path})


async def fetch_hosted(
    client: httpx.AsyncClient, sandbox_id: str, filename: str
) -> httpx.Response:
    return await client.get(f"/sandbox/{sandbox_id}/hosted/{filename}")
