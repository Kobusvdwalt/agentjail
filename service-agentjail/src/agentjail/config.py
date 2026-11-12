from pathlib import Path
from shutil import which
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from agentjail.sandbox.egress import parse_rule


def _find_nsjail() -> str:
    """Bundled path first, then fall back to PATH lookup."""
    bundled = Path("/opt/agentjail/bin/nsjail")
    if bundled.is_file():
        return str(bundled)
    return which("nsjail") or "nsjail"


def _find_egress() -> str:
    bundled = Path("/opt/agentjail/bin/agentjail-egress")
    if bundled.is_file():
        return str(bundled)
    return which("agentjail-egress") or "agentjail-egress"


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

    network_allow: list[str] = []
    """Hosts that sandboxes without `network: true` may reach through the
    egress proxy, e.g. `["api.github.com", "*.googleapis.com"]`. Empty keeps
    those sandboxes fully offline. See `agentjail.sandbox.egress`."""
    network_allow_private: bool = False
    """Let allowlisted hosts resolve to private and loopback addresses. For
    local development only; metadata addresses stay blocked."""
    egress_bin: str = _find_egress()
    egress_port: int = Field(default=3128, ge=1, le=65_535)
    egress_socket_dir: Path = Path("/tmp/agentjail-egress")

    @field_validator("network_allow")
    @classmethod
    def _valid_network_allow(cls, patterns: list[str]) -> list[str]:
        for pattern in patterns:
            parse_rule(pattern)
        return patterns
