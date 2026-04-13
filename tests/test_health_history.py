"""Tests for the container health history API endpoint and related storage."""
import sys
import os
import time
import pytest
import aiosqlite
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


# =============================================================================
# Helpers for rollup tests — real in-memory SQLite
# =============================================================================

async def _make_rollup_db():
    """Return an open in-memory aiosqlite connection with the health history schema."""
    db = await aiosqlite.connect(":memory:")
    await db.execute("""
        CREATE TABLE container_health_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            server_id INTEGER NOT NULL,
            container_name TEXT NOT NULL,
            is_running INTEGER NOT NULL DEFAULT 1,
            cpu_pct REAL DEFAULT 0,
            mem_pct REAL DEFAULT 0,
            recorded_at INTEGER NOT NULL,
            resolution_sec INTEGER NOT NULL DEFAULT 5,
            health_status TEXT DEFAULT NULL
        )
    """)
    await db.commit()
    return db


@asynccontextmanager
async def _wrap_db(db):
    yield db


def _db_getter(db):
    """Return a callable that behaves like get_db_connection() but reuses db."""
    return lambda: _wrap_db(db)


# =============================================================================
# API endpoint: /api/health/history/{server_id}
# =============================================================================


def _make_db_mock_with_rows(rows):
    """Build an aiosqlite mock that returns the given rows from fetchall."""
    mock_cursor = AsyncMock()
    mock_cursor.fetchall = AsyncMock(return_value=rows)

    mock_cursor_cm = AsyncMock()
    mock_cursor_cm.__aenter__ = AsyncMock(return_value=mock_cursor)
    mock_cursor_cm.__aexit__ = AsyncMock(return_value=False)

    mock_db = AsyncMock()
    mock_db.execute = MagicMock(return_value=mock_cursor_cm)

    mock_db_cm = AsyncMock()
    mock_db_cm.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db_cm.__aexit__ = AsyncMock(return_value=False)

    return MagicMock(return_value=mock_db_cm)


@pytest.mark.asyncio
@patch("api.routes.get_db_connection")
async def test_health_history_returns_grouped_by_container(mock_get_db):
    """Rows from DB must be grouped into per-container history lists."""
    from api.routes import api_health_history

    now = int(time.time())
    rows = [
        ("nginx", 1, 5.2, 12.4, now - 10),
        ("nginx", 1, 4.8, 11.9, now - 5),
        ("redis", 1, 0.5, 3.1, now - 10),
        ("redis", 0, 0.0, 0.0, now - 5),
    ]
    mock_get_db.return_value = _make_db_mock_with_rows(rows).return_value

    response = await api_health_history(server_id=1, minutes=60)
    data = response.body
    import json
    result = json.loads(data)

    assert len(result) == 2
    by_name = {c["container_name"]: c for c in result}

    assert "nginx" in by_name
    assert len(by_name["nginx"]["history"]) == 2
    assert all(p["is_running"] == 1 for p in by_name["nginx"]["history"])

    assert "redis" in by_name
    redis_states = [p["is_running"] for p in by_name["redis"]["history"]]
    assert 1 in redis_states
    assert 0 in redis_states


@pytest.mark.asyncio
@patch("api.routes.get_db_connection")
async def test_health_history_empty_returns_empty_list(mock_get_db):
    """No rows in DB → empty JSON list."""
    from api.routes import api_health_history

    mock_get_db.return_value = _make_db_mock_with_rows([]).return_value

    response = await api_health_history(server_id=1, minutes=60)
    import json
    result = json.loads(response.body)
    assert result == []


@pytest.mark.asyncio
@patch("api.routes.get_db_connection")
async def test_health_history_respects_minutes_param(mock_get_db):
    """The cutoff timestamp sent to the DB must reflect the minutes parameter."""
    from api.routes import api_health_history

    mock_get_db_fn = _make_db_mock_with_rows([])
    mock_get_db.return_value = mock_get_db_fn.return_value

    before = int(time.time())
    await api_health_history(server_id=1, minutes=30)
    after = int(time.time())

    # Retrieve the execute call args to check the cutoff
    mock_db = mock_get_db.return_value.__aenter__.return_value
    execute_call = mock_db.execute.call_args
    query, params = execute_call[0]
    cutoff = params[1]

    expected_min = before - 30 * 60
    expected_max = after - 30 * 60
    assert expected_min <= cutoff <= expected_max


@pytest.mark.asyncio
@patch("api.routes.get_db_connection")
async def test_health_history_includes_cpu_and_mem(mock_get_db):
    """Each history point must include cpu and mem for time-series charts (#88)."""
    from api.routes import api_health_history

    now = int(time.time())
    rows = [
        ("nginx", 1, 5.2, 12.4, now - 10),
        ("nginx", 1, 4.8, 11.9, now - 5),
    ]
    mock_get_db.return_value = _make_db_mock_with_rows(rows).return_value

    response = await api_health_history(server_id=1, minutes=60)
    import json
    result = json.loads(response.body)

    assert len(result) == 1
    points = result[0]["history"]
    assert len(points) == 2
    assert "cpu" in points[0], "History point must include 'cpu' for CPU time-series chart"
    assert "mem" in points[0], "History point must include 'mem' for memory time-series chart"
    assert points[0]["cpu"] == 5.2
    assert points[0]["mem"] == 12.4


# =============================================================================
# Rollup tests — real in-memory SQLite (SQL logic cannot be mocked)
# =============================================================================


@pytest.mark.asyncio
async def test_rollup_aggregates_old_raw_rows():
    """15 raw (5s) rows in one 1-min bucket older than 1h collapse to 1 row with resolution_sec=60."""
    from services.stats_engine import rollup_health_history

    db = await _make_rollup_db()
    try:
        now = int(time.time())
        # All rows land in the same 1-minute bucket, clearly older than 1 hour
        bucket_base = ((now - 4000) // 60) * 60  # floor to minute boundary
        rows = [
            (1, "nginx", 1, float(i), float(i * 2), bucket_base + i, 5, "healthy")
            for i in range(15)
        ]
        await db.executemany(
            "INSERT INTO container_health_history "
            "(server_id, container_name, is_running, cpu_pct, mem_pct, recorded_at, resolution_sec, health_status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        await db.commit()

        with patch("services.stats_engine.get_db_connection", side_effect=_db_getter(db)):
            await rollup_health_history()

        async with db.execute(
            "SELECT resolution_sec, COUNT(*) FROM container_health_history GROUP BY resolution_sec"
        ) as cur:
            by_res = {row[0]: row[1] for row in await cur.fetchall()}

        assert 5 not in by_res, "Raw rows should have been replaced"
        assert by_res.get(60) == 1, "Expected exactly 1 minute-averaged row"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_rollup_does_not_touch_recent_rows():
    """Raw rows newer than 1 hour must be left completely untouched by rollup."""
    from services.stats_engine import rollup_health_history

    db = await _make_rollup_db()
    try:
        now = int(time.time())
        recent_base = now - 1800  # 30 minutes ago — safely within the 1h window
        rows = [
            (1, "redis", 1, 2.0, 4.0, recent_base + i * 5, 5, None)
            for i in range(5)
        ]
        await db.executemany(
            "INSERT INTO container_health_history "
            "(server_id, container_name, is_running, cpu_pct, mem_pct, recorded_at, resolution_sec, health_status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        await db.commit()

        with patch("services.stats_engine.get_db_connection", side_effect=_db_getter(db)):
            await rollup_health_history()

        async with db.execute(
            "SELECT COUNT(*) FROM container_health_history WHERE resolution_sec = 5"
        ) as cur:
            count = (await cur.fetchone())[0]

        assert count == 5, "Recent raw rows must survive rollup unchanged"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_rollup_second_pass_aggregates_minute_rows():
    """1-minute rows older than 24h must be downsampled to 5-minute rows (resolution_sec=300)."""
    from services.stats_engine import rollup_health_history

    db = await _make_rollup_db()
    try:
        now = int(time.time())
        # Place several 1-min rows in one 5-min bucket, older than 24h
        bucket_base = ((now - 90000) // 300) * 300  # floor to 5-min boundary, >24h ago
        rows = [
            (1, "postgres", 1, 10.0 + j, 20.0 + j, bucket_base + j * 60, 60, None)
            for j in range(4)
        ]
        await db.executemany(
            "INSERT INTO container_health_history "
            "(server_id, container_name, is_running, cpu_pct, mem_pct, recorded_at, resolution_sec, health_status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        await db.commit()

        with patch("services.stats_engine.get_db_connection", side_effect=_db_getter(db)):
            await rollup_health_history()

        async with db.execute(
            "SELECT resolution_sec, COUNT(*) FROM container_health_history GROUP BY resolution_sec"
        ) as cur:
            by_res = {row[0]: row[1] for row in await cur.fetchall()}

        assert 60 not in by_res, "1-min rows should have been replaced"
        assert by_res.get(300) == 1, "Expected exactly 1 five-minute averaged row"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_rollup_prunes_beyond_7_days():
    """Any rows older than 7 days must be deleted regardless of resolution."""
    from services.stats_engine import rollup_health_history

    db = await _make_rollup_db()
    try:
        now = int(time.time())
        old_ts = now - 700000  # ~8 days ago
        await db.executemany(
            "INSERT INTO container_health_history "
            "(server_id, container_name, is_running, cpu_pct, mem_pct, recorded_at, resolution_sec, health_status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (1, "old-svc", 1, 5.0, 10.0, old_ts, 300, None),
                (1, "old-svc", 1, 6.0, 11.0, old_ts + 300, 300, None),
            ],
        )
        await db.commit()

        with patch("services.stats_engine.get_db_connection", side_effect=_db_getter(db)):
            await rollup_health_history()

        async with db.execute("SELECT COUNT(*) FROM container_health_history") as cur:
            count = (await cur.fetchone())[0]

        assert count == 0, "All rows older than 7 days must be pruned"
    finally:
        await db.close()


@pytest.mark.asyncio
@patch("api.routes.get_db_connection")
async def test_history_endpoint_accepts_large_minute_values(mock_get_db):
    """GET /api/health/history/1?minutes=10080 (7d) must return 200 with correct cutoff."""
    from api.routes import api_health_history

    mock_get_db.return_value = _make_db_mock_with_rows([]).return_value

    before = int(time.time())
    response = await api_health_history(server_id=1, minutes=10080)
    after = int(time.time())

    import json
    assert json.loads(response.body) == []

    mock_db = mock_get_db.return_value.__aenter__.return_value
    query, params = mock_db.execute.call_args[0]
    cutoff = params[1]

    expected_min = before - 10080 * 60
    expected_max = after - 10080 * 60
    assert expected_min <= cutoff <= expected_max, "Cutoff must reflect 7-day window"
