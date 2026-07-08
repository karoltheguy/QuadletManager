"""Covers uncovered branches in core/config_loader.py:
- dev_auto_login provided as a non-boolean (0/1 style) value
- malformed YAML that raises during load
"""
import pytest


@pytest.fixture
def clean_env(tmp_path, monkeypatch):
    monkeypatch.delenv("QUADLET_MASTER_KEY", raising=False)
    monkeypatch.delenv("DEV_AUTO_LOGIN", raising=False)
    return tmp_path


@pytest.mark.unit
def test_dev_auto_login_accepts_int_style(clean_env, monkeypatch):
    """A non-bool dev_auto_login value (int 1) is coerced via str(value) == '1'."""
    config_path = clean_env / "config.yaml"
    config_path.write_text("dev_auto_login: 1\n")
    monkeypatch.setenv("QUADLET_CONFIG_PATH", str(config_path))

    from core.config_loader import AppConfig

    assert AppConfig().dev_auto_login is True

    config_path.write_text("dev_auto_login: 0\n")
    assert AppConfig().dev_auto_login is False


@pytest.mark.unit
def test_malformed_yaml_is_handled(clean_env, monkeypatch):
    """A YAML parse error is caught and defaults are retained."""
    config_path = clean_env / "config.yaml"
    # Unclosed flow sequence -> yaml.safe_load raises YAMLError
    config_path.write_text("poll_frequency: [1, 2\n")
    monkeypatch.setenv("QUADLET_CONFIG_PATH", str(config_path))

    from core.config_loader import AppConfig

    config = AppConfig()
    # Falls back to defaults because the load failed
    assert config.poll_frequency == 10
    assert config.session_timeout == 3600
