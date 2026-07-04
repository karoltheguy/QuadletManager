import json
import os
import pytest


@pytest.mark.unit
def test_globals_dependency_is_exactly_pinned():
    """Verify devDependencies['globals'] uses an exact version, not a variant range."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    package_json_path = os.path.join(base_dir, "package.json")
    with open(package_json_path, "r") as f:
        package = json.load(f)

    version = package["devDependencies"]["globals"]

    assert not version.startswith(("^", "~", ">", "<", "*")), (
        f"globals version '{version}' is a variant range; pin to an exact version"
    )
