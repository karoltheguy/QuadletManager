import subprocess
import pytest

@pytest.mark.unit
def test_code_quality_pylint():
    """Verify that there are no unused imports, unused variables, or redefined built-ins.

    This targets both the core implementation files and the test files.
    """
    target_paths = [
        "services/systemd_manager.py",
        "script_ssh.py",
        "services/sync_engine.py",
        "api/routes.py",
        "import_servers.py",
        "tests/",
    ]
    
    # Run pylint with only our targeted rules enabled
    cmd = [
        "pylint", 
        "--disable=all", 
        "--enable=unused-import,unused-variable,redefined-builtin"
    ] + target_paths
    
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True
    )
    
    assert result.returncode == 0, (
        f"Pylint detected code quality issues:\n{result.stdout}"
    )


@pytest.mark.unit
def test_eslint_static_files():
    """Verify that ESLint runs successfully on the static JavaScript files using the codacy config."""
    cmd = [
        "npx",
        "eslint",
        "--config",
        ".codacy/tools-configs/eslint.config.mjs",
        "static/main.js"
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True
    )
    assert result.returncode == 0, (
        f"ESLint detected code quality issues:\n{result.stdout}\n{result.stderr}"
    )

