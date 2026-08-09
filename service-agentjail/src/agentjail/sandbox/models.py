from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from agentjail.sandbox.resources import ALL_RESOURCES


class SandboxConfig(BaseModel):
    name: str | None = None
    time_limit: int = 30
    memory_limit: int = 256
    pids_limit: int = 64
    env: dict[str, str] = Field(default_factory=dict)
    cwd: str = "/home"
    network: bool = False
    resources: list[str] = Field(default_factory=lambda: list(ALL_RESOURCES))
    """Glob patterns selecting which shared resources this sandbox can see.

    Matched against paths relative to the resources directory. Defaults to
    everything, so a sandbox created without an opinion behaves as it did before
    this field existed. See `agentjail.sandbox.resources`.
    """


class SandboxState(BaseModel):
    id: str
    name: str | None = None
    status: Literal["created", "running", "stopped"]
    config: SandboxConfig
    root_dir: str
    created_at: datetime
    updated_at: datetime


class ExecResult(BaseModel):
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False


class FileInfo(BaseModel):
    name: str
    path: str
    kind: Literal["file", "directory", "symlink", "other"]
    size: int
    mode: str
    modified: datetime


class StateFile(BaseModel):
    version: int = 1
    sandboxes: dict[str, SandboxState] = Field(default_factory=dict)
