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


async def exec_cmd(
    client: httpx.AsyncClient,
    sandbox_id: str,
    command: str,
    args: list[str] | None = None,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    timeout: int | None = None,
) -> dict:
    body: dict = {"command": command}
    if args is not None:
        body["args"] = args
    if cwd is not None:
        body["cwd"] = cwd
    if env is not None:
        body["env"] = env
    if timeout is not None:
        body["timeout"] = timeout
    resp = await client.post(f"/sandbox/{sandbox_id}/exec", json=body)
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
