"""The podman suite needs a fleet, not one server.

`tests/podman/conftest.py` currently registers exactly one server row per
test, so nothing in the podman suite ever exercises more than one host at a
time: no test can tell a per-server scope filter apart from a global one, and
nothing produces a real `stats_error` frame, because there is no second host
to be unreachable.

Issue #369 asks scripts/seed_test_db.py, behind QM_SEED_PODMAN, to also seed:

1. "Podman User Scope": the same address, ssh user and ssh_key_id as
   "Podman Host", but scope_filter 'user'. A second row on the same host lets
   a test assert that scope_filter actually narrows what gets polled, without
   the confound of also changing the key.
2. "Unreachable Host": same ssh user and ssh_key_id as "Podman Host", but on
   a dead port (a privileged port nothing binds to, so the failure is a
   deterministic connection-refused rather than a race). This is what lets
   fetch_server_stats() be tested against a real stats_error frame instead of
   a mocked one.

These tests run without a podman host: they only assert on the rows the
seeder writes into a throwaway database, never connect to anything.
"""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PODMAN_HOST_ADDRESS = "localhost:2223"


@pytest.fixture
def seeded_fleet(tmp_path):
    """Run scripts/seed_test_db.py with QM_SEED_PODMAN set, return rows by name."""
    db_path = tmp_path / "quadlets.db"

    async def _init_db():
        import core.database as d

        os.environ["QUADLET_DB_PATH"] = str(db_path)
        await d.init_db()

    import asyncio

    old_db_path = os.environ.get("QUADLET_DB_PATH")
    os.environ["QUADLET_DB_PATH"] = str(db_path)
    try:
        asyncio.run(_init_db())
    finally:
        if old_db_path is None:
            os.environ.pop("QUADLET_DB_PATH", None)
        else:
            os.environ["QUADLET_DB_PATH"] = old_db_path

    def _run_seeder():
        env = dict(os.environ)
        env["QUADLET_DB_PATH"] = str(db_path)
        env["QUADLET_MASTER_KEY"] = "0" * 64
        env["QM_SEED_PODMAN"] = "1"
        env["QM_PODMAN_HOST"] = PODMAN_HOST_ADDRESS
        env["PYTHONPATH"] = str(REPO_ROOT)
        result = subprocess.run(
            [sys.executable, "scripts/seed_test_db.py"],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"seed_test_db.py exited {result.returncode}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )

    def _read_rows():
        conn = sqlite3.connect(str(db_path))
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT id, name, ip_address, ssh_user, ssh_key_id, scope_filter FROM servers"
            )
            return {row["name"]: dict(row) for row in cursor.fetchall()}
        finally:
            conn.close()

    _run_seeder()
    return _run_seeder, _read_rows


def test_seeds_a_second_row_with_a_narrower_scope(seeded_fleet):
    _run_seeder, read_rows = seeded_fleet
    rows = read_rows()

    assert "Podman User Scope" in rows
    podman_host = rows["Podman Host"]
    user_scope_row = rows["Podman User Scope"]

    assert user_scope_row["scope_filter"] == "user"
    assert user_scope_row["ip_address"] == podman_host["ip_address"]
    assert user_scope_row["ssh_user"] == podman_host["ssh_user"]
    assert user_scope_row["ssh_key_id"] == podman_host["ssh_key_id"]


def test_seeds_an_unreachable_row_on_a_dead_port(seeded_fleet):
    _run_seeder, read_rows = seeded_fleet
    rows = read_rows()

    assert "Unreachable Host" in rows
    podman_host = rows["Podman Host"]
    unreachable_row = rows["Unreachable Host"]

    assert unreachable_row["ip_address"] == "localhost:1"
    assert unreachable_row["ssh_key_id"] == podman_host["ssh_key_id"]


def test_the_original_rows_are_unchanged(seeded_fleet):
    _run_seeder, read_rows = seeded_fleet
    rows = read_rows()

    podman_host = rows["Podman Host"]
    assert podman_host["scope_filter"] == "both"
    assert podman_host["ip_address"] == PODMAN_HOST_ADDRESS

    mock_server = rows["Mock Server"]
    assert mock_server["ssh_key_id"] is None


def test_reseeding_is_idempotent(seeded_fleet):
    run_seeder, read_rows = seeded_fleet
    names_after_first_run = sorted(read_rows().keys())

    run_seeder()

    names_after_second_run = sorted(read_rows().keys())
    assert names_after_second_run == names_after_first_run
    assert len(names_after_second_run) == len(set(names_after_second_run))
