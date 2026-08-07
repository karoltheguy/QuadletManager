"""Contract tests for the two-file dependency layout.

`requirements.in` / `requirements-test.in` hold the hand-edited ranges, whose
lower bounds are CVE-driven security floors. `requirements.txt` /
`requirements-test.txt` are the pip-compile locks: every direct and transitive
dependency pinned with `==` and hashed, and they are what CI, the container
image and start.sh install from.

Both halves need guarding. Floors that only live in a file nothing installs
would be decorative, and a lock that lost its hashes would silently drop the
supply-chain guarantee CI's `--require-hashes` is supposed to enforce.
"""

import os
import re

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# CVE-driven minimum versions. Raising one of these means editing the .in file
# and recompiling both locks.
SECURITY_FLOORS = {
    "asyncssh": (2, 14, 2),
    "cryptography": (48, 0, 1),
    "jinja2": (3, 1, 6),
    "python-multipart": (0, 0, 31),
}

LOCK_FILES = ["requirements.txt", "requirements-test.txt"]


def _read(filename):
    with open(os.path.join(BASE_DIR, filename), "r") as f:
        return f.read()


def parse_requirements(filepath):
    """Map {name: minimum version} for every `>=` line in an input file."""
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


def parse_lock(filename):
    """Map {name: pinned version} for every `==` pin in a compiled lock."""
    pins = {}
    for line in _read(filename).splitlines():
        match = re.match(r"^([A-Za-z0-9_.\-]+)==([^\s\\;]+)", line)
        if match:
            pins[match.group(1).lower()] = match.group(2)
    return pins


@pytest.mark.unit
def test_requirements_in_declares_security_floors():
    """requirements.in must keep the CVE-driven lower bounds."""
    reqs = parse_requirements(os.path.join(BASE_DIR, "requirements.in"))

    for name, floor in SECURITY_FLOORS.items():
        assert name in reqs, f"{name} lost its version floor in requirements.in"
        assert parse_version(reqs[name]) >= floor, (
            f"{name} minimum version {reqs[name]} is below the {floor} security floor"
        )


@pytest.mark.unit
def test_lock_satisfies_security_floors():
    """The resolved lock must actually install versions at or above the floors."""
    pins = parse_lock("requirements.txt")

    for name, floor in SECURITY_FLOORS.items():
        assert name in pins, f"{name} is missing from the requirements.txt lock"
        assert parse_version(pins[name]) >= floor, (
            f"requirements.txt pins {name}=={pins[name]}, below the {floor} security floor"
        )


@pytest.mark.unit
@pytest.mark.parametrize("filename", LOCK_FILES)
def test_lock_is_fully_hash_pinned(filename):
    """Every pin in a lock carries hashes, so --require-hashes cannot fail open."""
    content = _read(filename)
    pins = parse_lock(filename)
    assert pins, f"{filename} contains no pinned requirements"

    # A `name==version` line opens a continuation whose --hash lines follow, so
    # counting hashes per pin is enough to catch an unhashed entry.
    unhashed = [
        name for name in pins
        if not re.search(
            rf"^{re.escape(name)}==[^\s\\]+ *\\\n(?:\s*--hash=)",
            content,
            re.IGNORECASE | re.MULTILINE,
        )
    ]
    assert not unhashed, f"{filename} has pins without hashes: {sorted(unhashed)}"


@pytest.mark.unit
@pytest.mark.parametrize("filename", LOCK_FILES)
def test_lock_has_no_open_ranges(filename):
    """A `>=` surviving into a lock would defeat --require-hashes."""
    offenders = [
        line for line in _read(filename).splitlines()
        if not line.lstrip().startswith("#") and re.search(r"[><~!]=", line)
    ]
    assert not offenders, f"{filename} contains unpinned constraints: {offenders}"


@pytest.mark.unit
def test_locks_agree_on_shared_packages():
    """The two locks must never pin the same package to different versions."""
    base = parse_lock("requirements.txt")
    test = parse_lock("requirements-test.txt")

    conflicts = {
        name: (base[name], test[name])
        for name in set(base) & set(test)
        if base[name] != test[name]
    }
    assert not conflicts, f"locks disagree on shared packages: {conflicts}"
