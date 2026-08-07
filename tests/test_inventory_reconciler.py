"""Red-phase tests for reconcile_server_inventory.

These tests target the reconcile_server_inventory symbol which does not exist
yet in services/sync_engine.py:
  - reconcile_server_inventory(server_id, scope_filter)

Not-yet-existing symbols are imported inside each test function (not at
module level) so that a missing symbol produces a per-test failure with a
clear ImportError, instead of a collection error that would kill every test
in the file.
"""
from unittest.mock import AsyncMock, patch
import pytest

from core.database import get_db_connection


# =============================================================================
# 1. New file insertion with mtimes
# =============================================================================


@pytest.mark.asyncio
@pytest.mark.unit
@patch("services.sync_engine._fetch_mtimes", new_callable=AsyncMock)
@patch("services.sync_engine.fetch_all_quadlets", create=True, new_callable=AsyncMock)
async def test_reconcile_inserts_new_files_with_mtime(mock_fetch_all, mock_fetch_mtimes):
    """After one reconcile against a server whose scan returns two files,
    quadlets holds exactly one row per file and every row has a non-NULL
    last_known_mtime.
    """
    from services.sync_engine import reconcile_server_inventory

    async with get_db_connection() as db:
        await db.execute(
            "INSERT INTO servers (id, name, ip_address, ssh_user) VALUES (1, 's1', '10.0.0.1', 'root')"
        )
        await db.commit()

    scan_data = {
        "global": [
            {"path": "/etc/containers/systemd/web.container", "name": "web.container", "scope": "global"},
            {"path": "/etc/containers/systemd/db.container", "name": "db.container", "scope": "global"},
        ],
        "user": [],
    }
    mock_fetch_all.return_value = scan_data
    mock_fetch_mtimes.return_value = {
        "/etc/containers/systemd/web.container": 1000,
        "/etc/containers/systemd/db.container": 2000,
    }

    await reconcile_server_inventory(1, "global")

    async with get_db_connection() as db:
        async with db.execute(
            "SELECT file_path, scope, last_known_mtime FROM quadlets WHERE server_id = 1 ORDER BY file_path"
        ) as cur:
            rows = await cur.fetchall()

    assert len(rows) == 2
    paths = [r[0] for r in rows]
    assert "/etc/containers/systemd/db.container" in paths
    assert "/etc/containers/systemd/web.container" in paths
    for r in rows:
        assert r[2] is not None


# =============================================================================
# 2. Idempotency and preservation of existing values
# =============================================================================


@pytest.mark.asyncio
@pytest.mark.unit
@patch("services.sync_engine._fetch_mtimes", new_callable=AsyncMock)
@patch("services.sync_engine.fetch_all_quadlets", create=True, new_callable=AsyncMock)
async def test_reconcile_idempotent_preserves_existing_mtime_and_hash(mock_fetch_all, mock_fetch_mtimes):
    """Running reconcile twice with the same scan result produces no
    duplicate rows, and a row whose last_known_mtime and last_content_hash were
    set between the two runs still has those exact values afterwards.
    """
    from services.sync_engine import reconcile_server_inventory

    async with get_db_connection() as db:
        await db.execute(
            "INSERT INTO servers (id, name, ip_address, ssh_user) VALUES (1, 's1', '10.0.0.1', 'root')"
        )
        await db.commit()

    scan_data = {
        "global": [
            {"path": "/etc/containers/systemd/web.container", "name": "web.container", "scope": "global"}
        ],
        "user": [],
    }
    mock_fetch_all.return_value = scan_data
    mock_fetch_mtimes.return_value = {"/etc/containers/systemd/web.container": 1000}

    await reconcile_server_inventory(1, "global")

    async with get_db_connection() as db:
        await db.execute(
            "UPDATE quadlets SET last_known_mtime = 9999, last_content_hash = 'hash123' WHERE server_id = 1"
        )
        await db.commit()

    await reconcile_server_inventory(1, "global")

    async with get_db_connection() as db:
        async with db.execute(
            "SELECT file_path, last_known_mtime, last_content_hash FROM quadlets WHERE server_id = 1"
        ) as cur:
            rows = await cur.fetchall()

    assert len(rows) == 1
    assert rows[0][0] == "/etc/containers/systemd/web.container"
    assert rows[0][1] == 9999
    assert rows[0][2] == "hash123"


# =============================================================================
# 3. Deletion of absent files
# =============================================================================


@pytest.mark.asyncio
@pytest.mark.unit
@patch("services.sync_engine._fetch_mtimes", new_callable=AsyncMock)
@patch("services.sync_engine.fetch_all_quadlets", create=True, new_callable=AsyncMock)
async def test_reconcile_deletes_absent_files(mock_fetch_all, mock_fetch_mtimes):
    """A file present in the first scan but absent from the second has its
    row deleted by the second reconcile.
    """
    from services.sync_engine import reconcile_server_inventory

    async with get_db_connection() as db:
        await db.execute(
            "INSERT INTO servers (id, name, ip_address, ssh_user) VALUES (1, 's1', '10.0.0.1', 'root')"
        )
        await db.commit()

    first_scan = {
        "global": [
            {"path": "/etc/containers/systemd/web.container", "name": "web.container", "scope": "global"},
            {"path": "/etc/containers/systemd/old.container", "name": "old.container", "scope": "global"},
        ],
        "user": [],
    }
    second_scan = {
        "global": [
            {"path": "/etc/containers/systemd/web.container", "name": "web.container", "scope": "global"}
        ],
        "user": [],
    }

    mock_fetch_all.return_value = first_scan
    mock_fetch_mtimes.return_value = {
        "/etc/containers/systemd/web.container": 1000,
        "/etc/containers/systemd/old.container": 1000,
    }

    await reconcile_server_inventory(1, "global")

    async with get_db_connection() as db:
        async with db.execute("SELECT COUNT(*) FROM quadlets WHERE server_id = 1") as cur:
            row = await cur.fetchone()
    assert row[0] == 2

    mock_fetch_all.return_value = second_scan
    mock_fetch_mtimes.return_value = {"/etc/containers/systemd/web.container": 1000}

    await reconcile_server_inventory(1, "global")

    async with get_db_connection() as db:
        async with db.execute(
            "SELECT file_path FROM quadlets WHERE server_id = 1"
        ) as cur:
            rows = await cur.fetchall()

    assert len(rows) == 1
    assert rows[0][0] == "/etc/containers/systemd/web.container"


# =============================================================================
# 4. Exception handling
# =============================================================================


@pytest.mark.asyncio
@pytest.mark.unit
@patch("services.sync_engine.fetch_all_quadlets", create=True, new_callable=AsyncMock)
async def test_reconcile_handles_scan_exception_without_changing_rows(mock_fetch_all):
    """When fetch_all_quadlets raises an Exception, the existing rows for
    that server are still present and unchanged afterwards (assert it returns normally).
    """
    from services.sync_engine import reconcile_server_inventory

    async with get_db_connection() as db:
        await db.execute(
            "INSERT INTO servers (id, name, ip_address, ssh_user) VALUES (1, 's1', '10.0.0.1', 'root')"
        )
        await db.execute(
            "INSERT INTO quadlets (server_id, file_path, scope, last_known_mtime, last_content_hash) "
            "VALUES (1, '/etc/containers/systemd/web.container', 'global', 1234, 'hash_abc')"
        )
        await db.commit()

    mock_fetch_all.side_effect = RuntimeError("Scan connection failed")

    await reconcile_server_inventory(1, "global")

    async with get_db_connection() as db:
        async with db.execute(
            "SELECT file_path, scope, last_known_mtime, last_content_hash FROM quadlets WHERE server_id = 1"
        ) as cur:
            rows = await cur.fetchall()

    assert len(rows) == 1
    assert rows[0][0] == "/etc/containers/systemd/web.container"
    assert rows[0][1] == "global"
    assert rows[0][2] == 1234
    assert rows[0][3] == "hash_abc"


# =============================================================================
# 5. Integration with stats_engine._unit_names_for_scope
# =============================================================================


@pytest.mark.asyncio
@pytest.mark.unit
@patch("services.sync_engine._fetch_mtimes", new_callable=AsyncMock)
@patch("services.sync_engine.fetch_all_quadlets", create=True, new_callable=AsyncMock)
async def test_reconcile_populates_inventory_enabling_unit_names_lookup(mock_fetch_all, mock_fetch_mtimes):
    """After a reconcile whose scan returns /etc/containers/systemd/web.container
    in the "global" list, calling services.stats_engine._unit_names_for_scope(1, "global")
    returns ["web.service"], with NO quadlets rows inserted by the test itself.
    """
    from services.sync_engine import reconcile_server_inventory
    from services.stats_engine import _unit_names_for_scope

    async with get_db_connection() as db:
        await db.execute(
            "INSERT INTO servers (id, name, ip_address, ssh_user) VALUES (1, 's1', '10.0.0.1', 'root')"
        )
        await db.commit()

    scan_data = {
        "global": [
            {"path": "/etc/containers/systemd/web.container", "name": "web.container", "scope": "global"}
        ],
        "user": [],
    }
    mock_fetch_all.return_value = scan_data
    mock_fetch_mtimes.return_value = {"/etc/containers/systemd/web.container": 1000}

    await reconcile_server_inventory(1, "global")

    names = await _unit_names_for_scope(1, "global")
    assert names == ["web.service"]


# =============================================================================
# 6. Poll loop execution order
# =============================================================================


@pytest.mark.asyncio
@pytest.mark.unit
@patch("services.sync_engine.check_quadlets")
@patch("services.sync_engine.reconcile_all_inventories")
@patch("services.sync_engine.asyncio.sleep", new_callable=AsyncMock)
async def test_polling_loop_runs_reconcile_before_check_quadlets(
    mock_sleep, mock_reconcile, mock_check
):
    """Within one iteration of the poll cycle, reconcile_all_inventories runs
    immediately before check_quadlets.
    """
    import asyncio
    from services.sync_engine import polling_engine_loop

    order = []

    async def side_reconcile():
        order.append("reconcile")

    async def side_check():
        order.append("check")
        raise asyncio.CancelledError()

    mock_reconcile.side_effect = side_reconcile
    mock_check.side_effect = side_check

    with pytest.raises(asyncio.CancelledError):
        await polling_engine_loop()

    assert order == ["reconcile", "check"]


# =============================================================================
# 7. Resiliency across multiple registered servers
# =============================================================================


@pytest.mark.asyncio
@pytest.mark.unit
@patch("services.sync_engine.reconcile_server_inventory", new_callable=AsyncMock)
async def test_reconcile_all_inventories_continues_on_server_failure(
    mock_reconcile,
):
    """When reconcile_server_inventory raises for the first registered server,
    the second server is still reconciled.
    """
    from services.sync_engine import reconcile_all_inventories

    async with get_db_connection() as db:
        await db.execute(
            "INSERT INTO servers (id, name, ip_address, ssh_user, scope_filter) VALUES (1, 's1', '10.0.0.1', 'root', 'global')"
        )
        await db.execute(
            "INSERT INTO servers (id, name, ip_address, ssh_user, scope_filter) VALUES (2, 's2', '10.0.0.2', 'root', 'user')"
        )
        await db.commit()

    async def side_effect(server_id, scope_filter):
        if server_id == 1:
            raise RuntimeError("Server 1 failed")

    mock_reconcile.side_effect = side_effect

    await reconcile_all_inventories()

    assert mock_reconcile.call_count == 2
    mock_reconcile.assert_any_call(1, "global")
    mock_reconcile.assert_any_call(2, "user")

