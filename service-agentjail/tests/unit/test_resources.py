from pathlib import Path

from agentjail.sandbox.manager import SandboxManager, _parse_skill_frontmatter


class TestParseSkillFrontmatter:
    def test_valid_frontmatter(self, tmp_path):
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text(
            "---\nname: pdf-extractor\ndescription: Extract text from PDFs\n---\n# PDF Extractor\n"
        )
        result = _parse_skill_frontmatter(skill_md)
        assert result == {
            "name": "pdf-extractor",
            "description": "Extract text from PDFs",
        }

    def test_missing_name(self, tmp_path):
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("---\ndescription: no name field\n---\n")
        assert _parse_skill_frontmatter(skill_md) is None

    def test_missing_description(self, tmp_path):
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("---\nname: foo\n---\n")
        assert _parse_skill_frontmatter(skill_md) is None

    def test_no_frontmatter_marker(self, tmp_path):
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("# Just a markdown file\nNo frontmatter here.\n")
        assert _parse_skill_frontmatter(skill_md) is None

    def test_no_closing_marker(self, tmp_path):
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("---\nname: broken\ndescription: no closing\n")
        assert _parse_skill_frontmatter(skill_md) is None

    def test_invalid_yaml(self, tmp_path):
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("---\n: :\n  bad: [yaml\n---\n")
        assert _parse_skill_frontmatter(skill_md) is None

    def test_nonexistent_file(self, tmp_path):
        assert _parse_skill_frontmatter(tmp_path / "nope.md") is None

    def test_extra_fields_ignored(self, tmp_path):
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text(
            "---\nname: crawl\ndescription: Web crawler\nversion: '1.0'\ntags:\n  - web\n---\n"
        )
        result = _parse_skill_frontmatter(skill_md)
        assert result == {"name": "crawl", "description": "Web crawler"}


class TestListResources:
    def test_no_resources_dir(self, settings):
        manager = SandboxManager(settings)
        result = manager.list_resources()
        assert result == {"available": False, "files": [], "skills": []}

    def test_resources_dir_not_exists(self, settings):
        settings.resources_dir = Path("/nonexistent/path")
        manager = SandboxManager(settings)
        result = manager.list_resources()
        assert result == {"available": False, "files": [], "skills": []}

    def test_resources_dir_none(self, settings):
        settings.resources_dir = None
        manager = SandboxManager(settings)
        result = manager.list_resources()
        assert result == {"available": False, "files": [], "skills": []}

    def test_empty_dir(self, settings, tmp_path):
        resources = tmp_path / "resources"
        resources.mkdir()
        settings.resources_dir = resources
        manager = SandboxManager(settings)
        result = manager.list_resources()
        assert result == {"available": True, "files": [], "skills": []}

    def test_lists_files(self, settings, tmp_path):
        resources = tmp_path / "resources"
        resources.mkdir()
        (resources / "readme.txt").write_text("hi")
        (resources / "data").mkdir()
        (resources / "data" / "file.csv").write_text("a,b")
        settings.resources_dir = resources
        manager = SandboxManager(settings)
        result = manager.list_resources()
        assert result["available"] is True
        assert "readme.txt" in result["files"]
        assert "data/" in result["files"]
        assert "data/file.csv" in result["files"]

    def test_max_depth(self, settings, tmp_path):
        resources = tmp_path / "resources"
        resources.mkdir()
        deep = resources / "a" / "b" / "c"
        deep.mkdir(parents=True)
        (deep / "deep.txt").write_text("deep")
        (resources / "a" / "top.txt").write_text("top")
        settings.resources_dir = resources
        manager = SandboxManager(settings)
        result = manager.list_resources(max_depth=2)
        assert "a/top.txt" in result["files"]
        # depth 3+ should be excluded
        assert "a/b/c/" not in result["files"]
        assert "a/b/c/deep.txt" not in result["files"]

    def test_discovers_skills(self, settings, tmp_path):
        resources = tmp_path / "resources"
        skill_dir = resources / "pdf-extractor"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: pdf-extractor\ndescription: Extract PDFs\n---\n# PDF\n"
        )
        settings.resources_dir = resources
        manager = SandboxManager(settings)
        result = manager.list_resources()
        assert len(result["skills"]) == 1
        assert result["skills"][0]["name"] == "pdf-extractor"
        assert result["skills"][0]["description"] == "Extract PDFs"
        assert result["skills"][0]["location"] == "/resources/pdf-extractor/SKILL.md"

    def test_skill_with_bad_frontmatter_skipped(self, settings, tmp_path):
        resources = tmp_path / "resources"
        skill_dir = resources / "broken"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# No frontmatter\n")
        settings.resources_dir = resources
        manager = SandboxManager(settings)
        result = manager.list_resources()
        assert result["skills"] == []
        # But the file is still listed
        assert "broken/SKILL.md" in result["files"]
