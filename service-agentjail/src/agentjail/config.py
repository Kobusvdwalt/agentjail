from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentjailSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENTJAIL_")

    host: str = "0.0.0.0"
    port: int = 8000

    sandbox_base_dir: Path = Path("/var/lib/agentjail/sandboxes")
    state_file: Path = Path("/var/lib/agentjail/state.json")

    runner: Literal["nsjail", "chroot"] = "nsjail"
    nsjail_bin: str = "nsjail"

    default_time_limit: int = 30
    default_memory_limit: int = 256
    default_pids_limit: int = 64

    bind_mount_ro: list[str] = [
        "/usr",
        "/lib",
        "/lib64",
        "/bin",
        "/sbin",
        "/etc",
        "/sys/fs/cgroup",
    ]
