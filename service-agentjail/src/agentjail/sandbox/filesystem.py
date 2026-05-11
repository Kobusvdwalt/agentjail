from pathlib import Path


class PathTraversalError(Exception):
    pass


def _resolve_safe(root_dir: Path, user_path: str) -> Path:
    if "\x00" in user_path:
        raise PathTraversalError(f"Null byte in path: {user_path!r}")
    resolved = (root_dir / user_path.lstrip("/")).resolve()
    if not resolved.is_relative_to(root_dir.resolve()):
        raise PathTraversalError(f"Path escapes sandbox root: {user_path}")
    return resolved


def fs_resolve(root_dir: Path, path: str) -> Path:
    target = _resolve_safe(root_dir, path)
    if not target.is_file():
        raise FileNotFoundError(f"Not a file: {path}")
    return target


def fs_write(root_dir: Path, path: str, content: str | bytes) -> None:
    target = _resolve_safe(root_dir, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        target.write_bytes(content)
    else:
        target.write_text(content)
