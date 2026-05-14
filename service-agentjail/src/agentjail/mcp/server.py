from fastmcp import FastMCP

from agentjail.config import AgentjailSettings
from agentjail.sandbox.manager import SandboxManager

mcp = FastMCP("agentjail")

_manager: SandboxManager | None = None

# All tool names registered by this module (order matches decorators below).
ALL_TOOLS = [
    "sandbox_create",
    "sandbox_inspect",
    "sandbox_stop",
    "sandbox_remove",
    "sandbox_shell",
    "sandbox_download",
    "sandbox_resources",
]


def init_mcp(
    manager: SandboxManager, settings: AgentjailSettings | None = None
) -> FastMCP:
    global _manager
    _manager = manager

    if settings and settings.mcp_tools is not None:
        allowed = set(settings.mcp_tools)
        for tool_name in ALL_TOOLS:
            if tool_name not in allowed:
                try:
                    mcp.remove_tool(tool_name)
                except Exception:
                    pass  # tool may already be absent

    return mcp


def _get_manager() -> SandboxManager:
    assert _manager is not None, "MCP server not initialized — call init_mcp() first"
    return _manager


@mcp.tool(output_schema=None)
async def sandbox_create(
    name: str | None = None,
    time_limit: int = 30,
    memory_limit: int = 256,
    pids_limit: int = 64,
    env: dict[str, str] | None = None,
    cwd: str = "/home",
    network: bool = False,
) -> str:
    """Create and boot a persistent named sandbox. Returns sandbox state including the sandbox_id needed for all subsequent operations."""
    sandbox = await _get_manager().sandbox_create(
        name=name,
        time_limit=time_limit,
        memory_limit=memory_limit,
        pids_limit=pids_limit,
        env=env,
        cwd=cwd,
        network=network,
    )
    return sandbox.model_dump_json()


@mcp.tool(output_schema=None)
async def sandbox_inspect(sandbox_id: str) -> str:
    """Get detailed sandbox information including full configuration."""
    sandbox = await _get_manager().sandbox_inspect(sandbox_id)
    return sandbox.model_dump_json()


@mcp.tool(output_schema=None)
async def sandbox_stop(sandbox_id: str) -> str:
    """Stop a running sandbox."""
    sandbox = await _get_manager().sandbox_stop(sandbox_id)
    return sandbox.model_dump_json()


@mcp.tool(output_schema=None)
async def sandbox_remove(sandbox_id: str, force: bool = False) -> str:
    """Remove a stopped sandbox. Use force=True to remove a running sandbox."""
    await _get_manager().sandbox_remove(sandbox_id, force=force)
    return f'{{"status": "removed", "sandbox_id": "{sandbox_id}"}}'


@mcp.tool(output_schema=None)
async def sandbox_shell(
    sandbox_id: str,
    command: str,
    timeout: int | None = None,
) -> str:
    """Execute a shell command string with pipes, redirects, and shell syntax."""
    result = await _get_manager().sandbox_shell(sandbox_id, command, timeout=timeout)
    return result.model_dump_json()


@mcp.tool(output_schema=None)
async def sandbox_download(sandbox_id: str, path: str) -> str:
    """Prepare a file for download from the sandbox. Copies the file to a downloads folder with a unique name and returns a URL where it can be fetched.

    path: Absolute path inside the sandbox (e.g. /home/output.csv). The default working directory is /home, so files created by commands will typically be under /home/.
    """
    import json

    result = await _get_manager().sandbox_download(sandbox_id, path)
    return json.dumps(result)


@mcp.tool(output_schema=None)
async def sandbox_resources(max_depth: int = 2) -> str:
    """List shared read-only resource files available to all sandboxes at /resources.

    Returns a file listing (up to max_depth levels deep) and any discovered Agent Skills
    with their name, description, and location. To read a skill's full instructions,
    use sandbox_shell to cat the SKILL.md at the returned location.

    max_depth: Maximum directory depth to list (default 2).
    """
    import json

    result = _get_manager().list_resources(max_depth=max_depth)
    return json.dumps(result)
