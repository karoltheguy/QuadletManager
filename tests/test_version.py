import os
import subprocess

import pytest

import core.version
from core.version import (
    TagLookupError,
    ci_version,
    get_version,
    latest_tag,
    main,
    next_dev_version,
)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION_FILE = os.path.join(BASE_DIR, "VERSION")
DOCKERFILE = os.path.join(BASE_DIR, "Dockerfile")


@pytest.fixture(autouse=True)
def _clear_describe_version_cache():
    describe = getattr(core.version, "_describe_version", None)
    if describe is not None:
        describe.cache_clear()
    yield
    describe = getattr(core.version, "_describe_version", None)
    if describe is not None:
        describe.cache_clear()


@pytest.mark.unit
def test_get_version_prefers_app_version_env_var(monkeypatch):
    monkeypatch.setenv("APP_VERSION", "9.9.9+build.123")
    assert get_version() == "9.9.9+build.123"


@pytest.mark.unit
def test_get_version_uses_git_describe_when_no_env_var(monkeypatch):
    monkeypatch.delenv("APP_VERSION", raising=False)

    class FakeCompletedProcess:
        returncode = 0
        stdout = "v0.2.1-3-gabc1234\n"

    def fake_run(*args, **kwargs):
        return FakeCompletedProcess()

    monkeypatch.setattr(core.version.subprocess, "run", fake_run)

    assert get_version() == "0.2.1-3-gabc1234+dev"


@pytest.mark.unit
def test_get_version_falls_back_when_git_command_fails(monkeypatch):
    monkeypatch.delenv("APP_VERSION", raising=False)

    def fake_run(*args, **kwargs):
        raise subprocess.CalledProcessError(1, "git")

    monkeypatch.setattr(core.version.subprocess, "run", fake_run)

    assert get_version() == "0.0.0+dev"


@pytest.mark.unit
def test_get_version_falls_back_when_git_binary_missing(monkeypatch):
    monkeypatch.delenv("APP_VERSION", raising=False)

    def fake_run(*args, **kwargs):
        raise FileNotFoundError("git not found")

    monkeypatch.setattr(core.version.subprocess, "run", fake_run)

    assert get_version() == "0.0.0+dev"


@pytest.mark.unit
def test_no_version_file_at_repo_root():
    assert not os.path.exists(VERSION_FILE), (
        "VERSION file must not exist at repo root: the git tag is the single "
        "source of truth for the local-dev version, and this file must not come back"
    )


@pytest.mark.unit
def test_dockerfile_declares_app_version_build_arg():
    with open(DOCKERFILE, "r") as f:
        lines = [line.strip() for line in f]

    assert "ARG APP_VERSION=0.0.0+dev" in lines, (
        "Dockerfile must declare ARG APP_VERSION with a safe default for local builds. "
        "It must be a valid semver, not a bare word: an unparameterized local build "
        "renders this default in the profile menu, and `dev` showed up there as `vdev`"
    )
    assert "ENV APP_VERSION=${APP_VERSION}" in lines, (
        "Dockerfile must promote the APP_VERSION build arg to a runtime ENV var"
    )


def _tag(value):
    """Returns a tag_reader stub for ci_version()."""
    return lambda: value


# --- ci_version(), the release path. `:latest`, the semver image tags, and
# --- docs/RELEASING.md all rely on a tag build reporting its bare release
# --- version, with the run number confined to build metadata.


@pytest.mark.unit
def test_tag_build_puts_the_run_number_in_build_metadata():
    assert ci_version("tag", "v0.3.0", "520", _tag("v0.3.0")) == "0.3.0+build.520"


@pytest.mark.unit
def test_tag_build_does_not_consult_the_tag_reader():
    def explode():
        raise AssertionError("a tag build takes its version from the ref, not git describe")

    assert ci_version("tag", "v1.2.3", "520", explode) == "1.2.3+build.520"


@pytest.mark.unit
def test_tag_build_keeps_a_prerelease_tag_intact():
    assert ci_version("tag", "v0.3.0-rc.1", "520", _tag("v0.2.0")) == "0.3.0-rc.1+build.520"


# --- ci_version(), the dev path.


@pytest.mark.unit
def test_branch_build_is_a_prerelease_of_the_next_minor():
    assert ci_version("branch", "main", "514", _tag("v0.3.0")) == "0.4.0-dev.514"


@pytest.mark.unit
def test_dev_version_sorts_after_its_base_release_and_before_its_target():
    # The whole point of the prerelease form. `0.3.0+build.514`, the previous
    # scheme for dev builds, compared equal to the `0.3.0` release because
    # semver ignores build metadata for precedence.
    def key(version):
        core_version, _, pre = version.partition("-")
        major, minor, patch = (int(part) for part in core_version.split("."))
        # No prerelease sorts after the same core version that has one.
        return (major, minor, patch, pre == "", pre)

    assert key("0.3.0") < key("0.4.0-dev.514")
    assert key("0.4.0-dev.514") < key("0.4.0-dev.515")
    assert key("0.4.0-dev.515") < key("0.4.0")


@pytest.mark.unit
@pytest.mark.parametrize(
    "base,expected",
    [
        ("v0.2.0", "0.3.0-dev.7"),
        ("0.2.0", "0.3.0-dev.7"),  # leading `v` is optional
        ("v0.9.0", "0.10.0-dev.7"),  # minor is numeric, not lexical
        ("v1.4.9", "1.5.0-dev.7"),  # patch is reset, major is untouched
        ("v0.0.0", "0.1.0-dev.7"),  # the tagless fallback still bumps
    ],
)
def test_next_dev_version_bumps_the_minor(base, expected):
    assert next_dev_version(base, "7") == expected


@pytest.mark.unit
def test_next_dev_version_overshoots_a_prerelease_base():
    # Documented simplification: strictly this should target 0.4.0, but always
    # bumping is what keeps a dev version sorting after every existing tag.
    assert next_dev_version("v0.4.0-rc.1", "7") == "0.5.0-dev.7"


@pytest.mark.unit
def test_next_dev_version_ignores_build_metadata_on_the_base():
    assert next_dev_version("v0.4.0+build.3", "7") == "0.5.0-dev.7"


@pytest.mark.unit
def test_next_dev_version_falls_back_on_an_unparseable_base():
    assert next_dev_version("not-a-version", "7") == "0.0.0-dev.7"


# --- latest_tag(). A depth-1 checkout fetches no tags at all, which is the
# --- failure this fallback exists for.


@pytest.mark.unit
@pytest.mark.parametrize(
    "failure",
    [
        subprocess.CalledProcessError(128, "git"),
        FileNotFoundError("git not found"),
        subprocess.TimeoutExpired("git", 5),
    ],
)
def test_latest_tag_returns_none_when_git_describe_fails(monkeypatch, failure):
    def fake_run(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr(core.version.subprocess, "run", fake_run)

    assert latest_tag() is None


@pytest.mark.unit
@pytest.mark.parametrize("stdout,expected", [("\n", None), ("  v0.3.0  \n", "v0.3.0")])
def test_latest_tag_trims_output_and_returns_none_when_empty(monkeypatch, stdout, expected):
    class FakeCompletedProcess:
        returncode = 0
        stdout = ""

    FakeCompletedProcess.stdout = stdout

    monkeypatch.setattr(core.version.subprocess, "run", lambda *_a, **_k: FakeCompletedProcess())

    assert latest_tag() == expected


# --- A tagless checkout must fail the build, not invent a version. This is the
# --- regression `fetch-depth: 0` exists to prevent.


@pytest.mark.unit
def test_dev_build_raises_when_no_tag_can_be_read():
    with pytest.raises(TagLookupError, match="fetch-depth"):
        ci_version("branch", "main", "514", lambda: None)


@pytest.mark.unit
def test_tag_build_still_succeeds_without_any_tag_lookup():
    # The ref carries the version, so a tagless checkout must not break a release.
    assert ci_version("tag", "v0.3.0", "520", lambda: None) == "0.3.0+build.520"


@pytest.mark.unit
def test_main_exits_non_zero_and_explains_when_the_tag_lookup_fails(monkeypatch, capsys):
    monkeypatch.setattr(core.version, "latest_tag", lambda: None)
    monkeypatch.setenv("GITHUB_REF_TYPE", "branch")
    monkeypatch.setenv("GITHUB_REF_NAME", "main")
    monkeypatch.setenv("GITHUB_RUN_NUMBER", "514")

    assert main() == 1

    captured = capsys.readouterr()
    assert captured.out == "", "nothing may reach stdout, or CI captures it as the version"
    assert "fetch-depth" in captured.err


@pytest.mark.unit
def test_main_prints_only_the_version_on_success(monkeypatch, capsys):
    monkeypatch.setattr(core.version, "latest_tag", lambda: "v0.3.0")
    monkeypatch.setenv("GITHUB_REF_TYPE", "branch")
    monkeypatch.setenv("GITHUB_REF_NAME", "main")
    monkeypatch.setenv("GITHUB_RUN_NUMBER", "514")

    assert main() == 0
    assert capsys.readouterr().out == "0.4.0-dev.514\n"
