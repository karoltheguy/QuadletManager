"""Pylint code quality gate for unused imports, unused variables, and redefined builtins.

This gate lives in its own file because it requires only pylint, which is pinned
in requirements-test.txt and available in CI. The remaining checks in
test_code_quality.py require Codacy-generated tooling that CI does not have.
The conftest skip mechanism that protects those Codacy checks previously kept
this pylint check from running in CI.
"""
import pathlib
import subprocess
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).parent.parent


@pytest.mark.unit
def test_code_quality_pylint():
    """Verify that there are no unused imports, unused variables, or redefined built-ins.

    This targets both the core implementation files and the test files.
    """
    target_paths = [
        "services/systemd_manager.py",
        "scripts/script_ssh.py",
        "services/sync_engine.py",
        "api/routes.py",
        "scripts/import_servers.py",
        "tests/",
    ]

    # Run pylint with only our targeted rules enabled
    cmd = [
        sys.executable,
        "-m",
        "pylint",
        "--disable=all",
        "--enable=unused-import,unused-variable,redefined-builtin",
    ] + target_paths

    result = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, (
        f"Pylint detected code quality issues:\n{result.stdout}"
    )
