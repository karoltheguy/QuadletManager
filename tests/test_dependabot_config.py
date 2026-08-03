import os

import pytest
import yaml


def _dependabot_config_path():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, ".github", "dependabot.yml")


def _load_dependabot_config():
    path = _dependabot_config_path()
    assert os.path.isfile(path), f"{path} is missing"
    with open(path, "r") as f:
        return yaml.safe_load(f)


@pytest.mark.unit
def test_dependabot_config_file_exists():
    """Verify .github/dependabot.yml exists at the repo root's .github/
    directory, so Dependabot has a configuration to act on at all (see #200)."""
    path = _dependabot_config_path()
    assert os.path.isfile(path), f"{path} is missing"


@pytest.mark.unit
def test_dependabot_config_parses_as_yaml_dict():
    """Verify .github/dependabot.yml parses as valid YAML and yields a dict,
    not just a file containing the right substrings."""
    config = _load_dependabot_config()
    assert isinstance(config, dict), (
        "dependabot.yml must parse to a YAML mapping (dict)"
    )


@pytest.mark.unit
def test_dependabot_config_version_is_2():
    """Verify the top-level 'version' key equals the integer 2, as required
    by the Dependabot configuration file schema."""
    config = _load_dependabot_config()
    assert config.get("version") == 2, (
        f"top-level 'version' must equal integer 2, got {config.get('version')!r}"
    )


@pytest.mark.unit
def test_dependabot_config_has_nonempty_updates_list():
    """Verify a top-level 'updates' key exists and holds a non-empty list of
    update configurations."""
    config = _load_dependabot_config()
    updates = config.get("updates")
    assert isinstance(updates, list), (
        f"top-level 'updates' must be a non-empty list, got {updates!r}"
    )
    assert len(updates) > 0, (
        f"top-level 'updates' must be a non-empty list, got {updates!r}"
    )


def _updates_by_ecosystem():
    config = _load_dependabot_config()
    updates = config.get("updates") or []
    return {
        entry.get("package-ecosystem"): entry
        for entry in updates
        if isinstance(entry, dict)
    }


@pytest.mark.unit
def test_dependabot_config_covers_npm_pip_and_github_actions_ecosystems():
    """Verify all three required ecosystems (npm, pip, github-actions) are
    each represented by an entry in 'updates', matched on package-ecosystem
    (see #200)."""
    by_ecosystem = _updates_by_ecosystem()

    for ecosystem in ("npm", "pip", "github-actions"):
        assert ecosystem in by_ecosystem, (
            f"'updates' is missing an entry with package-ecosystem: {ecosystem}"
        )


@pytest.mark.unit
def test_dependabot_config_npm_entry_has_directory_and_weekly_schedule():
    """Verify the npm ecosystem entry has a 'directory' key and a 'schedule'
    dict with interval 'weekly'."""
    by_ecosystem = _updates_by_ecosystem()
    entry = by_ecosystem.get("npm")
    assert entry is not None, "'updates' is missing an entry with package-ecosystem: npm"

    assert "directory" in entry, "npm entry is missing a 'directory' key"

    schedule = entry.get("schedule")
    assert isinstance(schedule, dict), "npm entry is missing a 'schedule' mapping"
    assert schedule.get("interval") == "weekly", (
        f"npm entry's schedule.interval must be 'weekly', got {schedule.get('interval')!r}"
    )


@pytest.mark.unit
def test_dependabot_config_pip_entry_has_directory_and_weekly_schedule():
    """Verify the pip ecosystem entry has a 'directory' key and a 'schedule'
    dict with interval 'weekly'."""
    by_ecosystem = _updates_by_ecosystem()
    entry = by_ecosystem.get("pip")
    assert entry is not None, "'updates' is missing an entry with package-ecosystem: pip"

    assert "directory" in entry, "pip entry is missing a 'directory' key"

    schedule = entry.get("schedule")
    assert isinstance(schedule, dict), "pip entry is missing a 'schedule' mapping"
    assert schedule.get("interval") == "weekly", (
        f"pip entry's schedule.interval must be 'weekly', got {schedule.get('interval')!r}"
    )


@pytest.mark.unit
def test_dependabot_config_github_actions_entry_has_directory_and_weekly_schedule():
    """Verify the github-actions ecosystem entry has a 'directory' key and a
    'schedule' dict with interval 'weekly'."""
    by_ecosystem = _updates_by_ecosystem()
    entry = by_ecosystem.get("github-actions")
    assert entry is not None, (
        "'updates' is missing an entry with package-ecosystem: github-actions"
    )

    assert "directory" in entry, "github-actions entry is missing a 'directory' key"

    schedule = entry.get("schedule")
    assert isinstance(schedule, dict), "github-actions entry is missing a 'schedule' mapping"
    assert schedule.get("interval") == "weekly", (
        f"github-actions entry's schedule.interval must be 'weekly', got {schedule.get('interval')!r}"
    )
