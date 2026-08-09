"""Which resources a sandbox can see, and — the part that matters — cannot."""

from datetime import datetime, timezone

import pytest

from agentjail.sandbox.manager import SandboxManager
from agentjail.sandbox.models import SandboxConfig, SandboxState
from agentjail.sandbox.nsjail import NsjailRunner
from agentjail.sandbox.resources import matches, mount_roots, selected_paths


class TestMatches:
    def test_star_matches_everything(self):
        assert matches("a.txt", ["*"])
        assert matches("deep/nested/file.txt", ["*"])

    def test_exact_path(self):
        assert matches("vigil-api/SKILL.md", ["vigil-api/SKILL.md"])
        assert not matches("other/SKILL.md", ["vigil-api/SKILL.md"])

    def test_single_star_does_not_cross_directories(self):
        # The `.gitignore` intuition: `*` stays within one segment.
        assert matches("vigil-api/SKILL.md", ["vigil-api/*"])
        assert not matches("vigil-api/deep/SKILL.md", ["vigil-api/*"])

    def test_double_star_crosses_directories(self):
        assert matches("vigil-api/deep/nested/SKILL.md", ["vigil-api/**"])
        assert matches("vigil-api/SKILL.md", ["vigil-api/**"])

    def test_any_pattern_may_match(self):
        patterns = ["assistant/**", "shared/**"]
        assert matches("assistant/a.md", patterns)
        assert matches("shared/b.md", patterns)
        assert not matches("protocols/c.md", patterns)

    def test_empty_patterns_match_nothing(self):
        assert not matches("anything.txt", [])

    def test_wildcard_within_a_segment(self):
        assert matches("skill-one/SKILL.md", ["skill-*/SKILL.md"])
        assert not matches("other/SKILL.md", ["skill-*/SKILL.md"])


@pytest.fixture
def tree(tmp_path):
    """A resources directory shaped like the one this feature is for."""
    resources = tmp_path / "resources"

    for path, text in {
        "shared/common.md": "shared",
        "assistant/SKILL.md": "---\nname: assistant\ndescription: A\n---\n",
        "assistant/notes.md": "notes",
        "protocols/SKILL.md": "---\nname: protocols\ndescription: P\n---\n",
        "protocols/secret.md": "secret",
    }.items():
        file = resources / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text)

    return resources


class TestSelectedPaths:
    def test_star_selects_all(self, tree):
        selected = {path.as_posix() for path in selected_paths(tree, ["*"])}
        assert "assistant/SKILL.md" in selected
        assert "protocols/secret.md" in selected

    def test_subset_excludes_the_rest(self, tree):
        selected = {
            path.as_posix()
            for path in selected_paths(tree, ["assistant/**", "shared/**"])
        }
        assert "assistant/SKILL.md" in selected
        assert "shared/common.md" in selected
        assert "protocols/SKILL.md" not in selected
        assert "protocols/secret.md" not in selected

    def test_directories_on_the_way_are_kept(self, tree):
        # `assistant/` has to be walked to reach `assistant/SKILL.md`.
        selected = {
            path.as_posix() for path in selected_paths(tree, ["assistant/SKILL.md"])
        }
        assert "assistant" in selected
        assert "assistant/SKILL.md" in selected
        assert "assistant/notes.md" not in selected


class TestMountRoots:
    def test_fully_selected_directory_mounts_whole(self, tree):
        roots = {path.as_posix() for path in mount_roots(tree, ["assistant/**"])}
        assert roots == {"assistant"}

    def test_partial_directory_descends_to_files(self, tree):
        roots = {path.as_posix() for path in mount_roots(tree, ["assistant/SKILL.md"])}
        # Not `assistant`, which would carry `notes.md` in with it.
        assert roots == {"assistant/SKILL.md"}

    def test_excluded_directory_is_absent(self, tree):
        roots = {path.as_posix() for path in mount_roots(tree, ["assistant/**"])}
        assert not any(root.startswith("protocols") for root in roots)

    def test_partial_selection_nested_deeply(self, tmp_path):
        # The subtlest case: neither `a/` nor `a/b/` may be mounted whole,
        # because each holds a file the patterns exclude.
        base = tmp_path / "resources"
        for path in ("a/b/keep.md", "a/b/drop.md", "a/other.md"):
            file = base / path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text("x")

        roots = {path.as_posix() for path in mount_roots(base, ["a/b/keep.md"])}

        assert roots == {"a/b/keep.md"}

    def test_double_star_leading_pattern(self, tmp_path):
        base = tmp_path / "resources"
        for path in ("a/b/keep.md", "a/b/drop.md"):
            file = base / path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text("x")

        roots = {path.as_posix() for path in mount_roots(base, ["**/keep.md"])}

        assert roots == {"a/b/keep.md"}


class TestNsjailResourceMounts:
    """The mount is the boundary — a filtered listing alone would not hold."""

    def _sandbox(self, tmp_path, patterns):
        now = datetime.now(timezone.utc)
        return SandboxState(
            id="sandbox",
            status="running",
            config=SandboxConfig(resources=patterns),
            root_dir=str(tmp_path / "root"),
            created_at=now,
            updated_at=now,
        )

    def test_star_mounts_the_directory_once(self, settings, tree, tmp_path):
        settings.resources_dir = tree
        runner = NsjailRunner(settings)
        args = runner._resource_mounts(self._sandbox(tmp_path, ["*"]))
        assert args == ["--bindmount_ro", f"{tree}:/resources"]

    def test_subset_mounts_only_what_was_asked_for(self, settings, tree, tmp_path):
        settings.resources_dir = tree
        runner = NsjailRunner(settings)
        args = runner._resource_mounts(self._sandbox(tmp_path, ["assistant/**"]))
        joined = " ".join(args)
        assert f"{tree}/assistant:/resources/assistant" in joined
        assert "protocols" not in joined

    def test_no_patterns_mounts_nothing(self, settings, tree, tmp_path):
        settings.resources_dir = tree
        runner = NsjailRunner(settings)
        assert runner._resource_mounts(self._sandbox(tmp_path, [])) == []

    def test_absent_resources_dir_mounts_nothing(self, settings, tmp_path):
        settings.resources_dir = tmp_path / "nope"
        runner = NsjailRunner(settings)
        assert runner._resource_mounts(self._sandbox(tmp_path, ["*"])) == []


class TestListResourcesScoping:
    @pytest.mark.asyncio
    async def test_listing_is_scoped_to_the_sandbox(self, settings, tree):
        settings.resources_dir = tree
        manager = SandboxManager(settings)
        sandbox = await manager.sandbox_create(resources=["assistant/**"])

        result = manager.list_resources(sandbox_id=sandbox.id)

        assert "assistant/SKILL.md" in result["files"]
        assert "protocols/SKILL.md" not in result["files"]
        assert [skill["name"] for skill in result["skills"]] == ["assistant"]

    @pytest.mark.asyncio
    async def test_default_sandbox_sees_everything(self, settings, tree):
        settings.resources_dir = tree
        manager = SandboxManager(settings)
        sandbox = await manager.sandbox_create()

        result = manager.list_resources(sandbox_id=sandbox.id)

        assert "assistant/SKILL.md" in result["files"]
        assert "protocols/SKILL.md" in result["files"]

    @pytest.mark.asyncio
    async def test_empty_patterns_see_nothing(self, settings, tree):
        settings.resources_dir = tree
        manager = SandboxManager(settings)
        sandbox = await manager.sandbox_create(resources=[])

        result = manager.list_resources(sandbox_id=sandbox.id)

        assert result["files"] == []
        assert result["skills"] == []

    def test_without_a_sandbox_id_lists_everything(self, settings, tree):
        settings.resources_dir = tree
        manager = SandboxManager(settings)

        result = manager.list_resources()

        assert "protocols/SKILL.md" in result["files"]
