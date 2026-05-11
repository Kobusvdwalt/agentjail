import os
import stat
from datetime import datetime, timezone
from pathlib import Path

from agentjail.sandbox.models import FileInfo


class PathTraversalError(Exception):
    pass


def _resolve_safe(root_dir: Path, user_path: str) -> Path:
    if "\x00" in user_path:
        raise PathTraversalError(f"Null byte in path: {user_path!r}")
    resolved = (root_dir / user_path.lstrip("/")).resolve()
    if not resolved.is_relative_to(root_dir.resolve()):
        raise PathTraversalError(f"Path escapes sandbox root: {user_path}")
    return resolved


def fs_read(root_dir: Path, path: str) -> str:
    target = _resolve_safe(root_dir, path)
    return target.read_text()


def fs_write(root_dir: Path, path: str, content: str | bytes) -> None:
    target = _resolve_safe(root_dir, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        target.write_bytes(content)
    else:
        target.write_text(content)


def fs_mkdir(root_dir: Path, path: str) -> None:
    target = _resolve_safe(root_dir, path)
    target.mkdir(parents=True, exist_ok=True)


def fs_remove(root_dir: Path, path: str) -> None:
    target = _resolve_safe(root_dir, path)
    if target.is_dir():
        import shutil

        shutil.rmtree(target)
    else:
        target.unlink()


def fs_list(root_dir: Path, path: str = "/") -> list[FileInfo]:
    target = _resolve_safe(root_dir, path)
    entries = []
    for entry in target.iterdir():
        st = entry.lstat()
        entries.append(_stat_to_info(entry, st, root_dir))
    return entries


def fs_stat(root_dir: Path, path: str) -> FileInfo:
    target = _resolve_safe(root_dir, path)
    st = target.lstat()
    return _stat_to_info(target, st, root_dir)


def _stat_to_info(path: Path, st: os.stat_result, root_dir: Path) -> FileInfo:
    if stat.S_ISDIR(st.st_mode):
        kind = "directory"
    elif stat.S_ISLNK(st.st_mode):
        kind = "symlink"
    elif stat.S_ISREG(st.st_mode):
        kind = "file"
    else:
        kind = "other"

    rel = path.relative_to(root_dir.resolve())
    return FileInfo(
        name=path.name,
        path="/" + str(rel),
        kind=kind,
        size=st.st_size,
        mode=oct(stat.S_IMODE(st.st_mode)),
        modified=datetime.fromtimestamp(st.st_mtime, tz=timezone.utc),
    )
