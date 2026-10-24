import asyncio
import os
import signal

from agentjail.sandbox.models import ExecResult


async def _read(stream: asyncio.StreamReader, limit: int) -> tuple[str, bool]:
    retained = bytearray()
    truncated = False
    while chunk := await stream.read(65_536):
        retained.extend(chunk)
        if len(retained) > limit:
            del retained[:-limit]
            truncated = True
    return retained.decode(errors="replace"), truncated


def _kill_group(proc: asyncio.subprocess.Process) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


async def run_process(
    command: list[str],
    *,
    timeout: float,
    output_limit: int,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    stdin: bytes | None = None,
) -> ExecResult:
    spawn = asyncio.create_task(
        asyncio.create_subprocess_exec(
            *command,
            cwd=cwd,
            env=env,
            stdin=asyncio.subprocess.PIPE
            if stdin is not None
            else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
    )
    try:
        proc = await asyncio.shield(spawn)
    except asyncio.CancelledError:
        proc = await spawn
        _kill_group(proc)
        await proc.communicate()
        raise

    async def communicate():
        async with asyncio.TaskGroup() as group:
            stdout = group.create_task(_read(proc.stdout, output_limit))
            stderr = group.create_task(_read(proc.stderr, output_limit))
            if stdin is not None:
                proc.stdin.write(stdin)
                await proc.stdin.drain()
                proc.stdin.close()
            await proc.wait()
            _kill_group(proc)
        return stdout.result(), stderr.result()

    communication = asyncio.create_task(communicate())
    timed_out = False
    try:
        output = await asyncio.wait_for(asyncio.shield(communication), timeout)
    except TimeoutError:
        timed_out = True
        _kill_group(proc)
        output = await communication
    except asyncio.CancelledError:
        _kill_group(proc)
        await communication
        raise
    finally:
        _kill_group(proc)

    (stdout, stdout_truncated), (stderr, stderr_truncated) = output
    return ExecResult(
        exit_code=proc.returncode or 0,
        stdout=stdout,
        stderr=stderr,
        timed_out=timed_out,
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
    )
