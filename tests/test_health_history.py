"""Tests for the container health history API endpoint and related storage."""
import sys
import os
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


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
