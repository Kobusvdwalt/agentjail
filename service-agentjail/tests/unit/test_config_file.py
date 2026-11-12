"""The YAML config file: what it sets, what overrides it, and what it refuses."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from agentjail import config
from agentjail.config import CONFIG_FILE_ENV, AgentjailSettings

EXAMPLE = Path(__file__).parents[2] / "config" / "agentjail.example.yaml"


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    path = tmp_path / "agentjail.yaml"
    monkeypatch.setenv(CONFIG_FILE_ENV, str(path))
    return path


def test_settings_come_from_the_file(config_path):
    config_path.write_text(
        "network_allow:\n  - api.github.com\n  - '*.googleapis.com'\n"
        "default_time_limit: 45\nrunner: chroot\n"
    )
    settings = AgentjailSettings()
    assert settings.network_allow == ["api.github.com", "*.googleapis.com"]
    assert settings.default_time_limit == 45
    assert settings.runner == "chroot"


def test_environment_variables_override_the_file(config_path, monkeypatch):
    config_path.write_text("default_time_limit: 45\nnetwork_allow: [a.example.com]\n")
    monkeypatch.setenv("AGENTJAIL_DEFAULT_TIME_LIMIT", "60")
    monkeypatch.setenv("AGENTJAIL_NETWORK_ALLOW", '["b.example.com"]')
    settings = AgentjailSettings()
    assert settings.default_time_limit == 60
    assert settings.network_allow == ["b.example.com"]


def test_constructor_arguments_override_both(config_path, monkeypatch):
    config_path.write_text("default_time_limit: 45\n")
    monkeypatch.setenv("AGENTJAIL_DEFAULT_TIME_LIMIT", "60")
    assert AgentjailSettings(default_time_limit=90).default_time_limit == 90


def test_an_empty_file_changes_nothing(config_path):
    config_path.write_text("")
    assert AgentjailSettings().network_allow == []


def test_a_misspelled_key_fails_at_startup(config_path):
    config_path.write_text("network_alow: [api.github.com]\n")
    with pytest.raises(ValidationError, match="network_alow"):
        AgentjailSettings()


def test_an_invalid_value_fails_at_startup(config_path):
    config_path.write_text("network_allow: ['api.*.com']\n")
    with pytest.raises(ValidationError, match="Invalid network allow pattern"):
        AgentjailSettings()


def test_a_file_that_is_not_a_mapping_fails_clearly(config_path):
    config_path.write_text("- api.github.com\n")
    with pytest.raises(ValueError, match="must map setting names to values"):
        AgentjailSettings()


def test_an_explicit_path_that_does_not_exist_fails(tmp_path, monkeypatch):
    monkeypatch.setenv(CONFIG_FILE_ENV, str(tmp_path / "missing.yaml"))
    with pytest.raises(ValueError, match="not a file"):
        AgentjailSettings()


def test_without_a_file_the_defaults_apply(tmp_path, monkeypatch):
    monkeypatch.delenv(CONFIG_FILE_ENV, raising=False)
    monkeypatch.setattr(config, "DEFAULT_CONFIG_FILE", tmp_path / "absent.yaml")
    assert config.config_file() is None
    assert AgentjailSettings().default_time_limit == 30


def test_the_default_location_is_read_when_present(tmp_path, monkeypatch):
    monkeypatch.delenv(CONFIG_FILE_ENV, raising=False)
    default = tmp_path / "agentjail.yaml"
    default.write_text("max_active_commands: 4\n")
    monkeypatch.setattr(config, "DEFAULT_CONFIG_FILE", default)
    assert AgentjailSettings().max_active_commands == 4


def test_the_shipped_example_is_valid(monkeypatch):
    monkeypatch.setenv(CONFIG_FILE_ENV, str(EXAMPLE))
    settings = AgentjailSettings()
    assert "*.googleapis.com" in settings.network_allow
