"""Red-phase tests for cycle 2 of issue #265: wiring unit-state collection
into the stats poller.

These tests target symbols that do not exist yet in services/stats_engine.py:
  - ScopeResult namedtuple
  - _unit_names_for_scope()
  - a module-level sentinel constant used to batch podman ps + systemctl show
  - _record_unit_states()

Not-yet-existing symbols are imported inside each test function (not at
module level) so that a missing symbol produces a per-test failure with a
clear ImportError, instead of a collection error that would kill every test
in the file.
"""
import json
import time

import aiosqlite
import pytest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from services.stats_engine import (
    _fetch_scope_stats,
    fetch_server_stats,
    ROOTLESS_ENV_PREFIX,
)


# =============================================================================
# 1. ScopeResult namedtuple
# =============================================================================


@pytest.mark.unit
def test_scope_result_has_containers_and_unit_states_fields_in_order():
    """ScopeResult must be a namedtuple with exactly (containers, unit_states)."""
    from services.stats_engine import ScopeResult

    assert ScopeResult._fields == ("containers", "unit_states")


# =============================================================================
# 2. _unit_names_for_scope() -- real in-memory sqlite, mirrors
#    tests/test_health_history.py's _make_rollup_db / _wrap_db / _db_getter
# =============================================================================

_QUADLETS_TABLE_DDL = """
    CREATE TABLE quadlets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        server_id INTEGER NOT NULL,
        file_path TEXT NOT NULL,
        scope TEXT NOT NULL CHECK(scope IN ('global', 'user')),
        last_known_mtime INTEGER,
        last_content_hash TEXT
    )
"""


async def _make_quadlets_db(rows):
    """Return an open in-memory aiosqlite connection with a quadlets table
    pre-populated with rows: (server_id, file_path, scope)."""
    db = await aiosqlite.connect(":memory:")
    await db.execute(_QUADLETS_TABLE_DDL)
    await db.executemany(
        "INSERT INTO quadlets (server_id, file_path, scope) VALUES (?, ?, ?)",
        rows,
    )
    await db.commit()
    return db


@asynccontextmanager
async def _wrap_db(db):
    yield db


def _db_getter(db):
    """Return a callable that behaves like get_db_connection() but reuses db."""
    return lambda: _wrap_db(db)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_unit_names_for_scope_maps_container_file_to_unit_name():
    """A .container quadlet file_path must map to its systemd unit name."""
    from services.stats_engine import _unit_names_for_scope

    db = await _make_quadlets_db([
        (1, "/etc/containers/systemd/web.container", "global"),
    ])
    try:
        with patch("services.stats_engine.get_db_connection", side_effect=_db_getter(db)):
            names = await _unit_names_for_scope(1, "global")

        assert names == ["web.service"]
    finally:
        await db.close()


@pytest.mark.asyncio
@pytest.mark.unit
async def test_unit_names_for_scope_excludes_non_container_files():
    """.volume/.network/.pod quadlets must NOT be mapped to foo.service.

    Podman names those units foo-volume.service, foo-network.service,
    foo-pod.service etc, so deriving foo.service would query units that
    do not exist.
    """
    from services.stats_engine import _unit_names_for_scope

    db = await _make_quadlets_db([
        (1, "/etc/containers/systemd/web.container", "global"),
        (1, "/etc/containers/systemd/foo.volume", "global"),
        (1, "/etc/containers/systemd/foo.network", "global"),
        (1, "/etc/containers/systemd/foo.pod", "global"),
    ])
    try:
        with patch("services.stats_engine.get_db_connection", side_effect=_db_getter(db)):
            names = await _unit_names_for_scope(1, "global")

        assert names == ["web.service"]
        assert "foo.service" not in names
    finally:
        await db.close()


@pytest.mark.asyncio
@pytest.mark.unit
async def test_unit_names_for_scope_filters_by_server_id_and_scope():
    """Only rows matching both server_id AND scope must be returned."""
    from services.stats_engine import _unit_names_for_scope

    db = await _make_quadlets_db([
        (1, "/etc/containers/systemd/web.container", "global"),
        (1, "/etc/containers/systemd/app.container", "user"),
        (2, "/etc/containers/systemd/other.container", "global"),
    ])
    try:
        with patch("services.stats_engine.get_db_connection", side_effect=_db_getter(db)):
            names = await _unit_names_for_scope(1, "global")

        assert names == ["web.service"]
    finally:
        await db.close()


@pytest.mark.asyncio
@pytest.mark.unit
async def test_unit_names_for_scope_returns_empty_list_when_no_match():
    """No matching rows must yield an empty list, not an error."""
    from services.stats_engine import _unit_names_for_scope

    db = await _make_quadlets_db([
        (1, "/etc/containers/systemd/web.container", "user"),
    ])
    try:
        with patch("services.stats_engine.get_db_connection", side_effect=_db_getter(db)):
            names = await _unit_names_for_scope(1, "global")

        assert names == []
    finally:
        await db.close()


# =============================================================================
# 3. Sentinel-batched SSH in _fetch_scope_stats()
# =============================================================================


@pytest.mark.asyncio
@patch("services.stats_engine._unit_names_for_scope")
@patch("services.stats_engine.pool")
@pytest.mark.unit
async def test_fetch_scope_stats_batches_systemctl_with_podman_ps(mock_pool, mock_unit_names):
    """The systemctl show call must ride along in the SAME execute_command call
    as podman ps, keeping the call count at exactly 2 per scope."""
    from services.stats_engine import _UNIT_STATE_SENTINEL

    mock_unit_names.return_value = ["web.service"]

    ps_json = json.dumps([{"Names": "web", "HealthStatus": "healthy"}])
    systemctl_block = (
        "Id=web.service\n"
        "LoadState=loaded\n"
        "ActiveState=active\n"
        "SubState=running\n"
        "NRestarts=0"
    )
    first_stdout = f"{ps_json}\n{_UNIT_STATE_SENTINEL}\n{systemctl_block}"
    stats_json = json.dumps([{"name": "web", "cpu_percent": "1%", "mem_percent": "2%"}])

    mock_pool.execute_command = AsyncMock(side_effect=[first_stdout, stats_json])

    result = await _fetch_scope_stats(server_id=1, rootful=True)

    assert mock_pool.execute_command.call_count == 2

    first_call = mock_pool.execute_command.call_args_list[0]
    first_cmd = first_call[0][1]
    assert "podman ps" in first_cmd
    assert "systemctl show" in first_cmd

    assert "web.service" in result.unit_states
    assert result.unit_states["web.service"]["active_state"] == "active"

    assert len(result.containers) == 1
    assert result.containers[0]["name"] == "web"


@pytest.mark.asyncio
@patch("services.stats_engine._unit_names_for_scope")
@patch("services.stats_engine.pool")
@pytest.mark.unit
async def test_fetch_scope_stats_no_units_omits_systemctl(mock_pool, mock_unit_names):
    """When _unit_names_for_scope returns [], the first command must contain
    NO systemctl text, execute_command is still called twice, and unit_states
    is empty."""
    mock_unit_names.return_value = []

    ps_json = json.dumps([{"Names": "web", "HealthStatus": "healthy"}])
    stats_json = json.dumps([{"name": "web", "cpu_percent": "1%", "mem_percent": "2%"}])

    mock_pool.execute_command = AsyncMock(side_effect=[ps_json, stats_json])

    result = await _fetch_scope_stats(server_id=1, rootful=True)

    assert mock_pool.execute_command.call_count == 2

    first_call = mock_pool.execute_command.call_args_list[0]
    first_cmd = first_call[0][1]
    assert "systemctl" not in first_cmd

    assert result.unit_states == {}


# =============================================================================
# 4. _record_unit_states() -- latest-state UPSERT, real in-memory sqlite
# =============================================================================

_UNIT_STATE_TABLE_DDL = """
    CREATE TABLE unit_state (
        server_id INTEGER,
        unit_name TEXT,
        scope TEXT,
        load_state TEXT,
        active_state TEXT,
        sub_state TEXT,
        n_restarts INTEGER DEFAULT 0,
        recorded_at INTEGER,
        PRIMARY KEY (server_id, unit_name, scope)
    )
"""


async def _make_unit_state_db():
    db = await aiosqlite.connect(":memory:")
    await db.execute(_UNIT_STATE_TABLE_DDL)
    await db.commit()
    return db


@pytest.mark.asyncio
@pytest.mark.unit
async def test_record_unit_states_inserts_one_row_per_unit():
    """Calling once must insert one row per unit with the right column values."""
    from services.stats_engine import _record_unit_states

    db = await _make_unit_state_db()
    try:
        unit_states_by_scope = {
            "global": {
                "web.service": {
                    "load_state": "loaded",
                    "active_state": "active",
                    "sub_state": "running",
                    "n_restarts": 0,
                },
            },
        }
        with patch("services.stats_engine.get_db_connection", side_effect=_db_getter(db)):
            await _record_unit_states(1, unit_states_by_scope)

        async with db.execute(
            "SELECT server_id, unit_name, scope, load_state, active_state, sub_state, n_restarts "
            "FROM unit_state"
        ) as cur:
            rows = await cur.fetchall()

        assert len(rows) == 1
        row = rows[0]
        assert row[0] == 1
        assert row[1] == "web.service"
        assert row[2] == "global"
        assert row[3] == "loaded"
        assert row[4] == "active"
        assert row[5] == "running"
        assert row[6] == 0
    finally:
        await db.close()


@pytest.mark.asyncio
@pytest.mark.unit
async def test_record_unit_states_upserts_existing_row_in_place():
    """Calling again for the same unit with changed state must UPDATE that row
    in place: the table still holds exactly ONE row for (server_id, unit_name,
    scope), with the new values."""
    from services.stats_engine import _record_unit_states

    db = await _make_unit_state_db()
    try:
        first_states = {
            "global": {
                "web.service": {
                    "load_state": "loaded",
                    "active_state": "active",
                    "sub_state": "running",
                    "n_restarts": 0,
                },
            },
        }
        second_states = {
            "global": {
                "web.service": {
                    "load_state": "loaded",
                    "active_state": "failed",
                    "sub_state": "dead",
                    "n_restarts": 3,
                },
            },
        }
        with patch("services.stats_engine.get_db_connection", side_effect=_db_getter(db)):
            await _record_unit_states(1, first_states)
            await _record_unit_states(1, second_states)

        async with db.execute(
            "SELECT active_state, sub_state, n_restarts FROM unit_state "
            "WHERE server_id = 1 AND unit_name = 'web.service' AND scope = 'global'"
        ) as cur:
            rows = await cur.fetchall()

        assert len(rows) == 1
        assert rows[0][0] == "failed"
        assert rows[0][1] == "dead"
        assert rows[0][2] == 3
    finally:
        await db.close()


@pytest.mark.asyncio
@pytest.mark.unit
async def test_record_unit_states_same_name_different_scopes_are_separate_rows():
    """Units in different scopes with the same name must be separate rows."""
    from services.stats_engine import _record_unit_states

    db = await _make_unit_state_db()
    try:
        unit_states_by_scope = {
            "global": {
                "web.service": {
                    "load_state": "loaded",
                    "active_state": "active",
                    "sub_state": "running",
                    "n_restarts": 0,
                },
            },
            "user": {
                "web.service": {
                    "load_state": "loaded",
                    "active_state": "inactive",
                    "sub_state": "dead",
                    "n_restarts": 1,
                },
            },
        }
        with patch("services.stats_engine.get_db_connection", side_effect=_db_getter(db)):
            await _record_unit_states(1, unit_states_by_scope)

        async with db.execute("SELECT scope, active_state FROM unit_state ORDER BY scope") as cur:
            rows = await cur.fetchall()

        assert len(rows) == 2
        by_scope = {r[0]: r[1] for r in rows}
        assert by_scope["global"] == "active"
        assert by_scope["user"] == "inactive"
    finally:
        await db.close()


# =============================================================================
# 5. fetch_server_stats publishes a "units" key
# =============================================================================


def _make_db_mock(server_rows):
    """Build a mock that satisfies:
    async with get_db_connection() as db:
        async with db.execute(...) as cursor:
            rows = await cursor.fetchall()
    Mirrors tests/test_stats_engine.py's _make_db_mock.
    """
    mock_cursor = AsyncMock()
    mock_cursor.fetchall = AsyncMock(return_value=server_rows)

    mock_cursor_cm = AsyncMock()
    mock_cursor_cm.__aenter__ = AsyncMock(return_value=mock_cursor)
    mock_cursor_cm.__aexit__ = AsyncMock(return_value=False)

    mock_db = AsyncMock()
    mock_db.execute = MagicMock(return_value=mock_cursor_cm)

    mock_db_cm = AsyncMock()
    mock_db_cm.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db_cm.__aexit__ = AsyncMock(return_value=False)

    mock_get_db = MagicMock(return_value=mock_db_cm)
    return mock_get_db


@pytest.mark.asyncio
@patch("services.stats_engine._record_unit_states", new_callable=AsyncMock)
@patch("services.stats_engine._record_health_history", new_callable=AsyncMock)
@patch("services.stats_engine.publisher")
@patch("services.stats_engine._fetch_scope_stats")
@patch("services.stats_engine.get_db_connection")
@pytest.mark.unit
async def test_fetch_server_stats_publishes_units_key(
    mock_get_db, mock_fetch, mock_publisher, mock_record_health, mock_record_units
):
    """The published stats_update payload must contain a 'units' key alongside
    the existing server_id / server_name / containers keys, with 'containers'
    unchanged in shape."""
    from services.stats_engine import ScopeResult

    mock_get_db.side_effect = _make_db_mock([(1, "testbox")])

    user_containers = [{"name": "user-app", "cpu": "1%", "mem": "2%",
                        "mem_usage": "—", "net_io": "—", "block_io": "—", "pids": "1"}]
    global_containers = [{"name": "system-svc", "cpu": "3%", "mem": "4%",
                          "mem_usage": "—", "net_io": "—", "block_io": "—", "pids": "2"}]

    user_units = {"app.service": {"load_state": "loaded", "active_state": "active",
                                   "sub_state": "running", "n_restarts": 0}}
    global_units = {"svc.service": {"load_state": "loaded", "active_state": "failed",
                                     "sub_state": "dead", "n_restarts": 2}}

    mock_fetch.side_effect = [
        ScopeResult(user_containers, user_units),
        ScopeResult(global_containers, global_units),
    ]
    mock_publisher.publish = MagicMock()

    await fetch_server_stats()

    mock_publisher.publish.assert_called_once()
    call_args = mock_publisher.publish.call_args
    payload = call_args[0][1]

    assert "units" in payload
    assert len(payload["containers"]) == 2
    container_names = [c["name"] for c in payload["containers"]]
    assert "user-app" in container_names
    assert "system-svc" in container_names

    unit_names = [u["unit"] for u in payload["units"]]
    assert "app.service" in unit_names
    assert "svc.service" in unit_names

    for u in payload["units"]:
        assert set(["unit", "scope", "load_state", "active_state", "sub_state", "n_restarts"]).issubset(u.keys())


# =============================================================================
# 5. _record_unit_events() -- durable transitions into container_events
# =============================================================================


@pytest.mark.asyncio
@pytest.mark.unit
@patch("services.stats_engine.record_container_event", new_callable=AsyncMock)
async def test_record_unit_events_emits_failure_on_transition_to_failed(mock_record):
    """A unit entering the failed state must be recorded as a durable
    `failure` event keyed by the quadlet stem, matching how `api/routes.py`
    already keys user-initiated events.

    The event must also record which scope the unit came from, since the
    quadlet stem alone cannot distinguish a global `web.service` from a
    user `web.service`.
    """
    import services.stats_engine as se

    se._prev_unit_state_by_sid[1] = {
        ("global", "web.service"): {"active_state": "active", "n_restarts": 0},
    }
    try:
        await se._record_unit_events(1, {
            "global": {
                "web.service": {
                    "load_state": "loaded", "active_state": "failed",
                    "sub_state": "failed", "n_restarts": 0,
                },
            },
        })

        mock_record.assert_awaited_once_with(
            1, "web", "failure", triggered_by="poller", details="scope=global"
        )
    finally:
        se._prev_unit_state_by_sid.pop(1, None)


@pytest.mark.asyncio
@pytest.mark.unit
@patch("services.stats_engine.record_container_event", new_callable=AsyncMock)
async def test_record_unit_events_stays_silent_while_unit_remains_failed(mock_record):
    """A unit that simply stays failed must emit nothing after the initial
    transition, otherwise every 5-second poll would append a duplicate."""
    import services.stats_engine as se

    se._prev_unit_state_by_sid[1] = {
        ("global", "web.service"): {"active_state": "failed", "n_restarts": 0},
    }
    try:
        await se._record_unit_events(1, {
            "global": {
                "web.service": {
                    "load_state": "loaded", "active_state": "failed",
                    "sub_state": "failed", "n_restarts": 0,
                },
            },
        })

        mock_record.assert_not_awaited()
    finally:
        se._prev_unit_state_by_sid.pop(1, None)


@pytest.mark.asyncio
@pytest.mark.unit
@patch("services.stats_engine.record_container_event", new_callable=AsyncMock)
async def test_record_unit_events_emits_restart_when_counter_increases(mock_record):
    """NRestarts is monotonic, so a restart is an increase against the
    previous poll rather than any particular absolute value."""
    import services.stats_engine as se

    se._prev_unit_state_by_sid[1] = {
        ("user", "web.service"): {"active_state": "active", "n_restarts": 3},
    }
    try:
        await se._record_unit_events(1, {
            "user": {
                "web.service": {
                    "load_state": "loaded", "active_state": "active",
                    "sub_state": "running", "n_restarts": 5,
                },
            },
        })

        mock_record.assert_awaited_once_with(
            1, "web", "restart", triggered_by="poller", details="scope=user"
        )
    finally:
        se._prev_unit_state_by_sid.pop(1, None)


@pytest.mark.asyncio
@pytest.mark.unit
@patch("services.stats_engine.record_container_event", new_callable=AsyncMock)
async def test_record_unit_events_seeds_silently_on_first_poll(mock_record):
    """The first poll after process start has no baseline, so it must seed
    silently rather than replay every pre-existing failed unit as a fresh
    event."""
    import services.stats_engine as se

    se._prev_unit_state_by_sid.pop(2, None)
    try:
        await se._record_unit_events(2, {
            "global": {
                "web.service": {
                    "load_state": "loaded", "active_state": "failed",
                    "sub_state": "failed", "n_restarts": 7,
                },
            },
        })

        mock_record.assert_not_awaited()
    finally:
        se._prev_unit_state_by_sid.pop(2, None)


@pytest.mark.asyncio
@pytest.mark.unit
@patch("services.stats_engine.record_container_event", new_callable=AsyncMock)
async def test_record_unit_events_keeps_scopes_distinct(mock_record):
    """The same stem in both scopes is two genuinely different systemd units,
    so a failure in one must not be suppressed by the other's baseline."""
    import services.stats_engine as se

    se._prev_unit_state_by_sid[3] = {
        ("global", "web.service"): {"active_state": "failed", "n_restarts": 0},
        ("user", "web.service"): {"active_state": "active", "n_restarts": 0},
    }
    try:
        await se._record_unit_events(3, {
            "global": {
                "web.service": {"active_state": "failed", "n_restarts": 0},
            },
            "user": {
                "web.service": {"active_state": "failed", "n_restarts": 0},
            },
        })

        # Only the user-scope unit transitioned; the global one was already failed.
        mock_record.assert_awaited_once_with(
            3, "web", "failure", triggered_by="poller", details="scope=user"
        )
    finally:
        se._prev_unit_state_by_sid.pop(3, None)


@pytest.mark.asyncio
@pytest.mark.unit
@patch("services.stats_engine.record_container_event", new_callable=AsyncMock)
async def test_record_unit_events_skips_units_that_appear_mid_run(mock_record):
    """A unit with no entry in the previous poll has no baseline either, so
    it seeds rather than reporting its current state as a transition."""
    import services.stats_engine as se

    se._prev_unit_state_by_sid[4] = {
        ("global", "web.service"): {"active_state": "active", "n_restarts": 0},
    }
    try:
        await se._record_unit_events(4, {
            "global": {
                "web.service": {"active_state": "active", "n_restarts": 0},
                "newly-added.service": {"active_state": "failed", "n_restarts": 2},
            },
        })

        mock_record.assert_not_awaited()
    finally:
        se._prev_unit_state_by_sid.pop(4, None)
