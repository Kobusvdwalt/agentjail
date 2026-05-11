from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class SandboxConfig(BaseModel):
    name: str | None = None
    time_limit: int = 30
    memory_limit: int = 256
    pids_limit: int = 64
    env: dict[str, str] = Field(default_factory=dict)
    cwd: str = "/home"
    network: bool = False


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
