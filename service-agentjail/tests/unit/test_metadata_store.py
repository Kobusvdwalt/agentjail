from datetime import datetime, timezone

import pytest

from agentjail.sandbox.models import SandboxConfig, SandboxState
from agentjail.state import InvalidSandboxId, MetadataStore


def make_sandbox(sandbox_id: str, **config_kwargs) -> SandboxState:
    now = datetime.now(timezone.utc)
    return SandboxState(
        id=sandbox_id,
        name=config_kwargs.pop("name", None),
        status="running",
        config=SandboxConfig(**config_kwargs),
        root_dir=f"/var/lib/agentjail/sandboxes/{sandbox_id}",
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def store(tmp_path):
    return MetadataStore(tmp_path / "sandboxes")


class TestRoundTrip:
    def test_write_then_read(self, store):
        written = make_sandbox("abc", name="mine", network=True, env={"TOKEN": "x"})
        store.write(written)

        read = store.read("abc")
        assert read is not None
        assert read.id == "abc"
        assert read.name == "mine"
        # The fields _build_args depends on: losing network would silently
        # change what a sandbox can reach.
        assert read.config.network is True
        assert read.config.env == {"TOKEN": "x"}

    def test_read_unknown_is_none(self, store):
        assert store.read("nope") is None

    def test_write_is_idempotent(self, store):
        sandbox = make_sandbox("abc")
        store.write(sandbox)

        sandbox.status = "stopped"
        store.write(sandbox)

        read = store.read("abc")
        assert read is not None
        assert read.status == "stopped"


class TestIsolation:
    """One sandbox's metadata is independent of every other's."""

    def test_writes_do_not_disturb_each_other(self, store):
        store.write(make_sandbox("first", name="one"))
        store.write(make_sandbox("second", name="two"))

        assert store.read("first").name == "one"
        assert store.read("second").name == "two"

    def test_remove_leaves_others(self, store):
        store.write(make_sandbox("first"))
        store.write(make_sandbox("second"))

        store.remove("first")

        assert store.read("first") is None
        assert store.read("second") is not None

    def test_remove_unknown_is_silent(self, store):
        store.remove("never-existed")


class TestList:
    def test_empty_before_anything_is_written(self, store):
        assert store.list() == []

    def test_lists_what_was_written(self, store):
        store.write(make_sandbox("first"))
        store.write(make_sandbox("second"))

        assert {sandbox.id for sandbox in store.list()} == {"first", "second"}

    def test_skips_unreadable_metadata(self, store):
        store.write(make_sandbox("good"))
        store.path_for("truncated").write_text("{not json")

        assert [sandbox.id for sandbox in store.list()] == ["good"]

    def test_skips_empty_metadata(self, store):
        """A create that made the file but has not filled it in yet."""
        store.write(make_sandbox("good"))
        store.path_for("pending").write_text("")

        assert [sandbox.id for sandbox in store.list()] == ["good"]


class TestSandboxIdIsAPathComponent:
    """Ids reach this from the request path, and now name a file."""

    @pytest.mark.parametrize(
        "sandbox_id",
        ["../escape", "a/b", "..", ".", "", "a\\b", "a\x00b"],
    )
    def test_rejected(self, store, sandbox_id):
        with pytest.raises(InvalidSandboxId):
            store.path_for(sandbox_id)

    @pytest.mark.parametrize("sandbox_id", ["../escape", "a/b", "", "."])
    def test_read_answers_none_rather_than_raising(self, store, sandbox_id):
        assert store.read(sandbox_id) is None

    def test_traversal_cannot_write_outside_the_metadata_directory(
        self, store, tmp_path
    ):
        with pytest.raises(InvalidSandboxId):
            store.write(make_sandbox("../../escaped"))

        assert not (tmp_path / "escaped.json").exists()

    def test_token_urlsafe_ids_are_accepted(self, store):
        """The ids actually issued — urlsafe base64, so `-` and `_`."""
        sandbox_id = "E8nQb8j5yqbdR6vsVZ-MbyzHm_9yNJYjVCjIx6qtEdQ"
        store.write(make_sandbox(sandbox_id))

        assert store.read(sandbox_id) is not None


class TestMetadataLocation:
    def test_stored_outside_the_sandbox_tree(self, store, tmp_path):
        """`config.env` carries credentials, and downloads resolve against the
        sandbox root — so metadata must not live under it."""
        store.write(make_sandbox("abc", env={"TOKEN": "secret"}))

        sandbox_root = tmp_path / "sandboxes" / "abc"
        assert not any(sandbox_root.rglob("*.json")) if sandbox_root.exists() else True
        assert store.path_for("abc").is_relative_to(tmp_path / "meta")
