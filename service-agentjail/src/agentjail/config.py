from pathlib import Path
from shutil import which
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_nsjail() -> str:
    """Bundled path first, then fall back to PATH lookup."""
    bundled = Path("/opt/agentjail/bin/nsjail")
    if bundled.is_file():
        return str(bundled)
    return which("nsjail") or "nsjail"


class AgentjailSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENTJAIL_")

    host: str = "0.0.0.0"
    port: int = 8000
    api_token: SecretStr | None = Field(default=None, min_length=32)
    max_output_bytes: int = Field(default=65_536, ge=1, le=1_048_576)
    max_active_commands: int = Field(default=8, ge=1, le=128)

    sandbox_base_dir: Path = Path("/var/lib/agentjail/sandboxes")
    state_file: Path = Path("/var/lib/agentjail/state.json")

    runner: Literal["nsjail", "chroot", "bare"] = "nsjail"
    nsjail_bin: str = _find_nsjail()

    resources_dir: Path | None = Path("/var/lib/agentjail/resources")

    default_time_limit: int = Field(default=30, ge=1)
    default_memory_limit: int = Field(default=256, ge=1)
    default_pids_limit: int = Field(default=64, ge=1)

    max_time_limit: int = Field(default=3600, ge=1)
    max_memory_limit: int = Field(default=8192, ge=1)
    max_pids_limit: int = Field(default=1024, ge=1)

    bind_mount_ro: list[str] = [
        "/usr",
        "/lib",
        "/lib64",
        "/bin",
        "/sbin",
        "/etc",
        "/sys/fs/cgroup",
    ]

    mcp_tools: list[str] | None = None
    """Whitelist of MCP tool names to expose. None means all tools are enabled."""
