import os
import re
import pytest

from core.version import get_version

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION_FILE = os.path.join(BASE_DIR, "VERSION")
DOCKERFILE = os.path.join(BASE_DIR, "Dockerfile")

SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


@pytest.mark.unit
def test_version_file_exists_and_is_valid_semver():
    with open(VERSION_FILE, "r") as f:
        content = f.read().strip()

    assert SEMVER_RE.match(content), (
        f"VERSION file content '{content}' is not a plain X.Y.Z semver string"
    )


@pytest.mark.unit
def test_get_version_prefers_app_version_env_var(monkeypatch):
    monkeypatch.setenv("APP_VERSION", "9.9.9+build.123")
    assert get_version() == "9.9.9+build.123"


@pytest.mark.unit
def test_get_version_falls_back_to_version_file_with_dev_suffix(monkeypatch):
    monkeypatch.delenv("APP_VERSION", raising=False)
    with open(VERSION_FILE, "r") as f:
        base = f.read().strip()

    assert get_version() == f"{base}+dev"


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
