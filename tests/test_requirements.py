import os
import pytest

def parse_requirements(filepath):
    requirements = {}
    if not os.path.exists(filepath):
        return requirements
    with open(filepath, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ">=" in line:
                parts = line.split(">=")
                name = parts[0].strip().lower()
                version = parts[1].strip()
                requirements[name] = version
    return requirements

def parse_version(version_str):
    # Parse version strings like '2.14.0' into tuple (2, 14, 0)
    return tuple(int(x) for x in version_str.split("."))

@pytest.mark.unit
def test_requirements_pinning():
    """Verify that requirements.txt specifies safe minimum version bounds for dependencies."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    req_path = os.path.join(base_dir, "requirements.txt")
    reqs = parse_requirements(req_path)
    
    assert "asyncssh" in reqs
    assert "cryptography" in reqs
    assert "jinja2" in reqs
    assert "python-multipart" in reqs
    
    assert parse_version(reqs["asyncssh"]) >= (2, 14, 2), f"asyncssh minimum version {reqs['asyncssh']} is too low"
    assert parse_version(reqs["cryptography"]) >= (48, 0, 1), f"cryptography minimum version {reqs['cryptography']} is too low"
    assert parse_version(reqs["jinja2"]) >= (3, 1, 6), f"jinja2 minimum version {reqs['jinja2']} is too low"
    assert parse_version(reqs["python-multipart"]) >= (0, 0, 31), f"python-multipart minimum version {reqs['python-multipart']} is too low"
