from fastmcp import FastMCP

from agentjail.sandbox.manager import SandboxManager

mcp = FastMCP("agentjail")

_manager: SandboxManager | None = None


def init_mcp(manager: SandboxManager) -> FastMCP:
    global _manager
    _manager = manager
    return mcp


def _get_manager() -> SandboxManager:
    assert _manager is not None, "MCP server not initialized — call init_mcp() first"
    return _manager


@mcp.tool
async def sandbox_run(
    command: str,
    time_limit: int = 30,
    memory_limit: int = 256,
    env: dict[str, str] | None = None,
) -> str:
    """Create an ephemeral sandbox, run a command, return the output, and destroy it."""
    result, sandbox_id = await _get_manager().sandbox_run(
        command, time_limit=time_limit, memory_limit=memory_limit, env=env
    )
    return result.model_copy(
        update={"stdout": f"[sandbox_id={sandbox_id}]\n{result.stdout}"}
    ).model_dump_json()


@mcp.tool
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


@mcp.tool
async def sandbox_list() -> str:
    """List all sandboxes with their current status."""
    sandboxes = await _get_manager().sandbox_list()
    return f"[{','.join(s.model_dump_json() for s in sandboxes)}]"


@mcp.tool
async def sandbox_inspect(sandbox_id: str) -> str:
    """Get detailed sandbox information including full configuration."""
    sandbox = await _get_manager().sandbox_inspect(sandbox_id)
    return sandbox.model_dump_json()


@mcp.tool
async def sandbox_stop(sandbox_id: str) -> str:
    """Stop a running sandbox."""
    sandbox = await _get_manager().sandbox_stop(sandbox_id)
    return sandbox.model_dump_json()


@mcp.tool
async def sandbox_remove(sandbox_id: str, force: bool = False) -> str:
    """Remove a stopped sandbox. Use force=True to remove a running sandbox."""
    await _get_manager().sandbox_remove(sandbox_id, force=force)
    return f'{{"status": "removed", "sandbox_id": "{sandbox_id}"}}'


@mcp.tool
async def sandbox_exec(
    sandbox_id: str,
    command: str,
    args: list[str] | None = None,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    timeout: int | None = None,
) -> str:
    """Execute a command with arguments inside a running sandbox."""
    result = await _get_manager().sandbox_exec(
        sandbox_id, command, args=args, cwd=cwd, env=env, timeout=timeout
    )
    return result.model_dump_json()


@mcp.tool
async def sandbox_shell(
    sandbox_id: str,
    command: str,
    timeout: int | None = None,
) -> str:
    """Execute a shell command string with pipes, redirects, and shell syntax."""
    result = await _get_manager().sandbox_shell(sandbox_id, command, timeout=timeout)
    return result.model_dump_json()
