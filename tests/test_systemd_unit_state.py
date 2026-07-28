"""Tests for services/systemd_manager.py unit-state polling (Issue #265).

Covers the pure parser `parse_systemctl_show` and the async fetcher
`fetch_unit_states`, following the async-test patterns established in
tests/test_stats_engine.py.
"""
import pytest
from unittest.mock import AsyncMock, patch

from services.systemd_manager import parse_systemctl_show, fetch_unit_states
from services.stats_engine import ROOTLESS_ENV_PREFIX


# =============================================================================
# parse_systemctl_show - pure sync parser tests
# =============================================================================


@pytest.mark.unit
def test_two_block_example_parses_both_units():
    output = (
        "Id=web.service\n"
        "LoadState=loaded\n"
        "ActiveState=active\n"
        "SubState=running\n"
        "NRestarts=3\n"
        "\n"
        "Id=db.service\n"
        "LoadState=not-found\n"
        "ActiveState=inactive\n"
        "SubState=dead\n"
        "NRestarts=0\n"
    )

    result = parse_systemctl_show(output)

    assert result["web.service"] == {
        "load_state": "loaded",
        "active_state": "active",
        "sub_state": "running",
        "n_restarts": 3,
    }
    assert result["db.service"] == {
        "load_state": "not-found",
        "active_state": "inactive",
        "sub_state": "dead",
        "n_restarts": 0,
    }
    assert isinstance(result["web.service"]["n_restarts"], int)
    assert isinstance(result["db.service"]["n_restarts"], int)


@pytest.mark.unit
def test_missing_nrestarts_defaults_to_zero():
    output = (
        "Id=web.service\n"
        "LoadState=loaded\n"
        "ActiveState=active\n"
        "SubState=running\n"
    )

    result = parse_systemctl_show(output)

    assert result["web.service"]["n_restarts"] == 0


@pytest.mark.unit
def test_not_found_load_state_is_returned_not_dropped():
    output = (
        "Id=ghost.service\n"
        "LoadState=not-found\n"
        "ActiveState=inactive\n"
        "SubState=dead\n"
        "NRestarts=0\n"
    )

    result = parse_systemctl_show(output)

    assert "ghost.service" in result
    assert result["ghost.service"]["load_state"] == "not-found"


@pytest.mark.unit
def test_empty_input_returns_empty_dict():
    assert parse_systemctl_show("") == {}


@pytest.mark.unit
def test_whitespace_only_input_returns_empty_dict():
    assert parse_systemctl_show("   \n\n   \n") == {}


@pytest.mark.unit
def test_stray_line_without_equals_is_ignored():
    output = (
        "some stray line with no equals sign\n"
        "Id=web.service\n"
        "LoadState=loaded\n"
        "ActiveState=active\n"
        "SubState=running\n"
        "NRestarts=1\n"
    )

    result = parse_systemctl_show(output)

    assert result["web.service"]["n_restarts"] == 1


# =============================================================================
# fetch_unit_states - async fetcher tests
# =============================================================================


@pytest.mark.asyncio
@patch("services.systemd_manager.pool")
@pytest.mark.unit
async def test_user_scope_uses_env_prefix_and_no_sudo(mock_pool):
    stdout = (
        "Id=web.service\n"
        "LoadState=loaded\n"
        "ActiveState=active\n"
        "SubState=running\n"
        "NRestarts=0\n"
    )
    mock_pool.execute_command = AsyncMock(return_value=stdout)

    await fetch_unit_states(1, ["web.service"], scope="user")

    call = mock_pool.execute_command.call_args
    cmd = call[0][1]
    assert ROOTLESS_ENV_PREFIX in cmd
    assert "systemctl --user show" in cmd
    assert call.kwargs.get("use_sudo") is not True


@pytest.mark.asyncio
@patch("services.systemd_manager.pool")
@pytest.mark.unit
async def test_global_scope_uses_sudo_and_no_env_prefix(mock_pool):
    stdout = (
        "Id=web.service\n"
        "LoadState=loaded\n"
        "ActiveState=active\n"
        "SubState=running\n"
        "NRestarts=0\n"
    )
    mock_pool.execute_command = AsyncMock(return_value=stdout)

    await fetch_unit_states(1, ["web.service"], scope="global")

    call = mock_pool.execute_command.call_args
    cmd = call[0][1]
    assert "systemctl show" in cmd
    assert "--user" not in cmd
    assert ROOTLESS_ENV_PREFIX not in cmd
    assert call.kwargs.get("use_sudo") is True


@pytest.mark.asyncio
@patch("services.systemd_manager.pool")
@pytest.mark.unit
async def test_command_includes_property_list_and_unit_names(mock_pool):
    stdout = (
        "Id=web.service\n"
        "LoadState=loaded\n"
        "ActiveState=active\n"
        "SubState=running\n"
        "NRestarts=0\n"
        "\n"
        "Id=db.service\n"
        "LoadState=loaded\n"
        "ActiveState=active\n"
        "SubState=running\n"
        "NRestarts=0\n"
    )
    mock_pool.execute_command = AsyncMock(return_value=stdout)

    for scope in ("user", "global"):
        mock_pool.execute_command.reset_mock()
        await fetch_unit_states(1, ["web.service", "db.service"], scope=scope)

        cmd = mock_pool.execute_command.call_args[0][1]
        assert "--property=Id,LoadState,ActiveState,SubState,NRestarts" in cmd
        assert "web.service" in cmd
        assert "db.service" in cmd


@pytest.mark.asyncio
@patch("services.systemd_manager.pool")
@pytest.mark.unit
async def test_empty_unit_names_returns_empty_dict_without_calling_execute_command(mock_pool):
    mock_pool.execute_command = AsyncMock(return_value="")

    result = await fetch_unit_states(1, [], scope="user")

    assert result == {}
    mock_pool.execute_command.assert_not_called()


@pytest.mark.asyncio
@patch("services.systemd_manager.pool")
@pytest.mark.unit
async def test_invalid_unit_name_raises_value_error_without_calling_execute_command(mock_pool):
    mock_pool.execute_command = AsyncMock(return_value="")

    with pytest.raises(ValueError):
        await fetch_unit_states(1, ["web.service; rm -rf /"], scope="user")

    mock_pool.execute_command.assert_not_called()


@pytest.mark.asyncio
@patch("services.systemd_manager.pool")
@pytest.mark.unit
async def test_return_value_equals_parsed_dict(mock_pool):
    stdout = (
        "Id=web.service\n"
        "LoadState=loaded\n"
        "ActiveState=active\n"
        "SubState=running\n"
        "NRestarts=7\n"
    )
    mock_pool.execute_command = AsyncMock(return_value=stdout)

    result = await fetch_unit_states(1, ["web.service"], scope="global")

    assert result == parse_systemctl_show(stdout)
