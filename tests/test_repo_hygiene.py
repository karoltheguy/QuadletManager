"""Repository hygiene checks that need git itself to answer.

SQLite writes `<name>-wal` and `<name>-shm` beside the database file. They hold
transient state for one process and are rewritten or removed whenever the app
or a test run touches the database, so a tracked copy shows up as a spurious
deletion in `git status` after any e2e run. `.gitignore` already ignores `*.db`,
but that pattern does not match the sidecars.
"""
import pathlib
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).parent.parent

pytestmark = pytest.mark.skipif(
    not (REPO_ROOT / ".git").exists(),
    reason="not a git checkout, so there is no index to inspect",
)


def _tracked_files():
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.splitlines()


@pytest.mark.unit
def test_no_sqlite_sidecar_files_are_tracked():
    """A tracked -wal or -shm file dirties the tree on every run that opens the DB."""
    sidecars = [
        path for path in _tracked_files()
        if path.endswith("-wal") or path.endswith("-shm")
    ]
    assert sidecars == [], (
        f"SQLite sidecar files must not be tracked, found: {sidecars}. "
        "Remove them with `git rm --cached` and keep the .gitignore entries."
    )


@pytest.mark.unit
def test_gitignore_covers_sqlite_sidecars():
    """Untracking alone is not enough; the next run would re-add them."""
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    entries = {line.strip() for line in gitignore}
    for pattern in ("*.db-wal", "*.db-shm"):
        assert pattern in entries, f".gitignore must contain {pattern!r}"
