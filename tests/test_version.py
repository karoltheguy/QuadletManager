import os
import subprocess

import pytest

import core.version
from core.version import get_version

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

    assert "ARG APP_VERSION=dev" in lines, (
        "Dockerfile must declare ARG APP_VERSION with a safe default for local builds"
    )
    assert "ENV APP_VERSION=${APP_VERSION}" in lines, (
        "Dockerfile must promote the APP_VERSION build arg to a runtime ENV var"
    )
