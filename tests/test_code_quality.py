import subprocess
import pytest

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


@pytest.mark.unit
def test_no_eslint_object_injection():
    """Verify that there are no ESLint object-injection warnings in static/main.js."""
    import json
    import os
    import shutil
    cli_path = shutil.which("codacy-analysis")
    if not cli_path:
        fallback = os.path.expanduser("~/.npm-global/bin/codacy-analysis")
        if os.path.exists(fallback):
            cli_path = fallback
        else:
            pytest.skip("codacy-analysis not found in PATH or ~/.npm-global/bin/")
    output_file = "test_results.json"
    if os.path.exists(output_file):
        os.remove(output_file)
    cmd = [
        cli_path,
        "analyze",
        "static/main.js",
        "--output-format",
        "json",
        "--output",
        output_file
    ]
    subprocess.run(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    assert os.path.exists(output_file), "Analysis output file was not created."
    with open(output_file, "r") as f:
        data = json.load(f)
    issues = data.get("issues", [])
    object_injection_issues = [
        issue for issue in issues
        if issue.get("patternId") == "ESLint9_security_detect-object-injection"
    ]
    assert len(object_injection_issues) == 0, (
        f"Detected {len(object_injection_issues)} ESLint object-injection warnings in static/main.js:\n"
        f"{json.dumps(object_injection_issues, indent=2)}"
    )

