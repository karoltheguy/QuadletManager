import pytest
from unittest.mock import AsyncMock, patch
from services.systemd_manager import systemctl_action, reload_and_restart

@pytest.fixture
def mock_pool():
    with patch("services.systemd_manager.pool") as m:
        m.execute_command = AsyncMock()
        yield m

@pytest.mark.asyncio
@pytest.mark.unit
async def test_systemctl_action_invalid_action():
    with pytest.raises(ValueError, match="Invalid systemctl action"):
        await systemctl_action(1, "format-drive", "unit.service")

@pytest.mark.asyncio
@pytest.mark.unit
async def test_systemctl_action_global(mock_pool):
    mock_pool.execute_command.return_value = "success"
    res = await systemctl_action(1, "start", "nginx.service", scope="global")
    assert res == "success"
    mock_pool.execute_command.assert_called_once_with(1, "systemctl start nginx.service", use_sudo=True)

@pytest.mark.asyncio
@pytest.mark.unit
async def test_systemctl_action_user(mock_pool):
    mock_pool.execute_command.return_value = "success"
    res = await systemctl_action(1, "stop", "nginx.service", scope="user")
    assert res == "success"
    mock_pool.execute_command.assert_called_once_with(1, "systemctl --user stop nginx.service", use_sudo=False)

@pytest.mark.asyncio
@pytest.mark.unit
async def test_systemctl_action_rejects_injection(mock_pool):
    with pytest.raises(ValueError, match="Invalid unit name"):
        await systemctl_action(1, "status", "nginx.service; rm -rf /", scope="user")
    mock_pool.execute_command.assert_not_called()

@pytest.mark.asyncio
@pytest.mark.unit
async def test_systemctl_action_quotes_template_instance(mock_pool):
    mock_pool.execute_command.return_value = "success"
    await systemctl_action(1, "status", "foo@bar.service", scope="user")
    mock_pool.execute_command.assert_called_once_with(
        1, "systemctl --user status foo@bar.service", use_sudo=False
    )

@pytest.mark.asyncio
@pytest.mark.unit
async def test_systemctl_action_daemon_reload(mock_pool):
    await systemctl_action(1, "daemon-reload", "")
    mock_pool.execute_command.assert_called_once_with(1, "systemctl daemon-reload", use_sudo=True)

@pytest.mark.asyncio
@pytest.mark.unit
async def test_systemctl_action_failure_not_allowed(mock_pool):
    mock_pool.execute_command.side_effect = Exception("ssh failed")
    with pytest.raises(Exception, match="ssh failed"):
        await systemctl_action(1, "start", "nginx.service", allow_failure=False)

@pytest.mark.asyncio
@pytest.mark.unit
async def test_systemctl_action_failure_allowed(mock_pool):
    mock_pool.execute_command.side_effect = Exception("ssh failed")
    res = await systemctl_action(1, "start", "nginx.service", allow_failure=True)
    assert "ssh failed" not in res
    assert "(warning:" in res

@pytest.mark.asyncio
@pytest.mark.unit
async def test_reload_and_restart():
    with patch("services.systemd_manager.systemctl_action") as mock_action:
        mock_action.return_value = None
        await reload_and_restart(1, "nginx.service", scope="user")
        assert mock_action.call_count == 2
        mock_action.assert_any_call(1, "daemon-reload", "", scope="user", allow_failure=True)
        mock_action.assert_any_call(1, "restart", "nginx.service", scope="user", allow_failure=True)
