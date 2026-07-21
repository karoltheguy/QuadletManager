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


@pytest.mark.unit
def test_quadlet_lint_is_pinned_and_vendored_on_install():
    """Verify quadlet-lint is declared as an exact-pinned dependency and that
    a `postinstall` script wires it into copy-assets, so the vendored build
    at static/vendor/quadlet-lint/ appears automatically in local dev, CI,
    and the Docker image without ever being committed. A Dependabot version
    bump should require no manual step to re-vendor the asset (see #198)."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    package_json_path = os.path.join(base_dir, "package.json")
    with open(package_json_path, "r") as f:
        package = json.load(f)

    assert "quadlet-lint" in package["dependencies"], (
        "quadlet-lint must be declared in package.json dependencies"
    )

    version = package["dependencies"]["quadlet-lint"]
    assert not version.startswith(("^", "~", ">", "<", "*")), (
        f"quadlet-lint version '{version}' is a variant range; pin to an exact version"
    )

    assert "postinstall" in package["scripts"], (
        "package.json scripts must define a postinstall hook to vendor quadlet-lint"
    )
    assert "copy-assets" in package["scripts"]["postinstall"], (
        "postinstall script must reference copy-assets so the vendored build is copied automatically"
    )
