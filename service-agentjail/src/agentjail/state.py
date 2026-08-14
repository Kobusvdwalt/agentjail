import json
import os
import tempfile
from pathlib import Path

from agentjail.sandbox.models import SandboxState

METADATA_DIRNAME = "meta"


class InvalidSandboxId(Exception):
    """A sandbox id that cannot name a directory — a separator, or empty."""


class MetadataStore:
    """Sandbox metadata, one file per sandbox, keyed by id.

    One file per sandbox instead of one registry for all of them, because a
    single registry is a single writer: every create rewrites the whole fleet's
    state, correct only as long as the lock serialising it works, and a network
    filesystem — the reason to want several agentjails at once — is exactly
    where that assumption stops being safe. Here two processes write the same
    file only when working on the same sandbox, which the API gives them no way
    to do: ids are unguessable and issued one at a time.

    Kept in `meta/`, a sibling of `sandboxes/`, rather than inside the sandbox
    it describes. The filesystem API resolves downloads against the sandbox
    root, so metadata stored under that root would be readable through it — and
    `config.env` holds whatever credential the sandbox was created with. The
    separation is what keeps that unreachable.

    Writes are atomic: a temporary file in the same directory, renamed into
    place. A reader sees the previous metadata or the next, never half of one.
    """

    def __init__(self, base_dir: Path) -> None:
        self._meta_dir = base_dir.parent / METADATA_DIRNAME

    @property
    def directory(self) -> Path:
        return self._meta_dir

    def path_for(self, sandbox_id: str) -> Path:
        """Where `sandbox_id`'s metadata lives, if the id can name a file.

        The id is a path component here, which it was not when one file held
        every sandbox keyed by a string — so an id like `../../etc` now reaches
        outside the metadata directory, and ids arrive from the request path.
        `secrets.token_urlsafe` never produces one, but nothing constrains the
        API to ids it issued.

        Rejected rather than sanitised: a caller passing a separator is not
        making a typo that a rewrite would fix.
        """
        if not sandbox_id or sandbox_id in (".", ".."):
            raise InvalidSandboxId(sandbox_id)
        if "/" in sandbox_id or "\\" in sandbox_id or "\x00" in sandbox_id:
            raise InvalidSandboxId(sandbox_id)
        return self._meta_dir / f"{sandbox_id}.json"

    def write(self, sandbox: SandboxState) -> None:
        path = self.path_for(sandbox.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(sandbox.model_dump_json(indent=2))
            os.replace(tmp_path, path)
        except BaseException:
            os.unlink(tmp_path)
            raise

    def read(self, sandbox_id: str) -> SandboxState | None:
        """The sandbox, or None if it does not exist.

        Unreadable metadata is None rather than an exception: a directory whose
        metadata is missing or corrupt cannot be run in, and the caller's answer
        to both is the same 404.
        """
        try:
            raw = self.path_for(sandbox_id).read_text()
        except (InvalidSandboxId, OSError, ValueError):
            return None
        if not raw.strip():
            return None
        try:
            return SandboxState.model_validate(json.loads(raw))
        except ValueError:
            return None

    def remove(self, sandbox_id: str) -> None:
        """Forget a sandbox. Silent if it was already gone."""
        try:
            self.path_for(sandbox_id).unlink(missing_ok=True)
        except (InvalidSandboxId, OSError):
            pass

    def list(self) -> list[SandboxState]:
        """Every sandbox with readable metadata, oldest first.

        Unreadable files are skipped rather than raised: a create writes its
        metadata after making the directory, and a listing taken in between
        should not fail over a sandbox nobody can use yet.
        """
        try:
            entries = sorted(self._meta_dir.glob("*.json"))
        except OSError:
            return []

        sandboxes = [
            sandbox
            for entry in entries
            if (sandbox := self.read(entry.stem)) is not None
        ]
        sandboxes.sort(key=lambda sandbox: sandbox.created_at)
        return sandboxes
