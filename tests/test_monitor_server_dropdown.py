"""Tests for GET /api/servers/options, the Monitor pane's server dropdown.

The dropdown is server inventory, so it is fed from the database and only
refreshed when the inventory changes. It used to be rebuilt from the stats
cache on every SSE frame, which destroyed the options underneath an open
native dropdown and swallowed the user's click (issue #365).
"""
import os
import sys
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tests.test_server_key_dropdown import _AioDualMock


def _mock_servers(mock_db, rows):
    conn_mock = MagicMock()
    conn_mock.execute = MagicMock(return_value=_AioDualMock(fetchall_result=rows))
    mock_db.return_value.__aenter__ = AsyncMock(return_value=conn_mock)
    mock_db.return_value.__aexit__ = AsyncMock(return_value=False)
    return conn_mock


@pytest.mark.asyncio
@pytest.mark.unit
@patch('api.routes.get_db_connection')
async def test_servers_options_returns_placeholder_then_every_server(mock_db):
    from api.routes import api_servers_options

    _mock_servers(mock_db, [(3, "prod"), (1, "staging")])

    body = (await api_servers_options(request=MagicMock())).body.decode()

    assert body == (
        '<option value="">Select a server...</option>'
        '<option value="3">prod</option>'
        '<option value="1">staging</option>'
    )


@pytest.mark.asyncio
@pytest.mark.unit
@patch('api.routes.get_db_connection')
async def test_servers_options_orders_by_position(mock_db):
    """The dropdown must list servers in the same order as the Navigator."""
    from api.routes import api_servers_options

    conn_mock = _mock_servers(mock_db, [])
    await api_servers_options(request=MagicMock())

    query = conn_mock.execute.call_args[0][0]
    assert "ORDER BY position" in query


@pytest.mark.asyncio
@pytest.mark.unit
@patch('api.routes.get_db_connection')
async def test_servers_options_escapes_the_server_name(mock_db):
    """Server names are free text, so they cannot go into HTML unescaped."""
    from api.routes import api_servers_options

    _mock_servers(mock_db, [(1, '<img src=x onerror="alert(1)">')])

    body = (await api_servers_options(request=MagicMock())).body.decode()

    assert "<img" not in body
    assert "&lt;img" in body


@pytest.mark.asyncio
@pytest.mark.unit
@patch('api.routes.get_db_connection')
async def test_servers_options_with_no_servers_returns_only_the_placeholder(mock_db):
    from api.routes import api_servers_options

    _mock_servers(mock_db, [])

    body = (await api_servers_options(request=MagicMock())).body.decode()

    assert body == '<option value="">Select a server...</option>'
