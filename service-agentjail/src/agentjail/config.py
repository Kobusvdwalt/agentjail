from pathlib import Path
from shutil import which
from typing import Literal

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

    sandbox_base_dir: Path = Path("/var/lib/agentjail/sandboxes")
    state_file: Path = Path("/var/lib/agentjail/state.json")

    runner: Literal["nsjail", "chroot"] = "nsjail"
    nsjail_bin: str = _find_nsjail()

    resources_dir: Path | None = Path("/var/lib/agentjail/resources")

    default_time_limit: int = 30
    default_memory_limit: int = 256
    default_pids_limit: int = 64

    max_time_limit: int = 3600
    max_memory_limit: int = 8192
    max_pids_limit: int = 1024

    bind_mount_ro: list[str] = [
        "/usr",
        "/lib",
        "/lib64",
        "/bin",
        "/sbin",
        "/etc",
        "/sys/fs/cgroup",
    ]
