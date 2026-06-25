import pytest
from unittest.mock import AsyncMock, patch
from services.tree_scanner import scan_directory, fetch_all_quadlets, GLOBAL_DIR, USER_DIR

@pytest.fixture
def mock_pool():
    with patch("services.tree_scanner.pool") as m:
        m.execute_command = AsyncMock()
        yield m

@pytest.mark.asyncio
async def test_scan_directory_success_global(mock_pool):
    mock_pool.execute_command.return_value = "/etc/containers/systemd/app.container\n/etc/containers/systemd/db.volume\n"
    res = await scan_directory(1, GLOBAL_DIR, use_sudo=True)
    assert len(res) == 2
    assert res[0]["name"] == "app.container"
    assert res[0]["scope"] == "global"
    assert res[1]["name"] == "db.volume"
    assert res[1]["scope"] == "global"

@pytest.mark.asyncio
async def test_scan_directory_success_user(mock_pool):
    mock_pool.execute_command.return_value = "~/.config/containers/systemd/my.pod\n"
    res = await scan_directory(1, USER_DIR, use_sudo=False)
    assert len(res) == 1
    assert res[0]["name"] == "my.pod"
    assert res[0]["scope"] == "user"

@pytest.mark.asyncio
async def test_scan_directory_empty(mock_pool):
    mock_pool.execute_command.return_value = "\n"
    res = await scan_directory(1, USER_DIR, use_sudo=False)
    assert len(res) == 0

@pytest.mark.asyncio
async def test_scan_directory_error(mock_pool):
    mock_pool.execute_command.side_effect = Exception("SSH error")
    res = await scan_directory(1, USER_DIR, use_sudo=False)
    assert res == []

@pytest.mark.asyncio
async def test_fetch_all_quadlets_both():
    with patch("services.tree_scanner.scan_directory") as mock_scan:
        mock_scan.side_effect = [
            [{"name": "global_app.container"}],
            [{"name": "user_app.container"}]
        ]
        res = await fetch_all_quadlets(1, scope_filter="both")
        assert len(res["global"]) == 1
        assert len(res["user"]) == 1
        assert mock_scan.call_count == 2

@pytest.mark.asyncio
async def test_fetch_all_quadlets_global():
    with patch("services.tree_scanner.scan_directory") as mock_scan:
        mock_scan.side_effect = [[{"name": "global_app.container"}]]
        res = await fetch_all_quadlets(1, scope_filter="global")
        assert len(res["global"]) == 1
        assert len(res["user"]) == 0
        assert mock_scan.call_count == 1

@pytest.mark.asyncio
async def test_fetch_all_quadlets_user():
    with patch("services.tree_scanner.scan_directory") as mock_scan:
        mock_scan.side_effect = [[{"name": "user_app.container"}]]
        res = await fetch_all_quadlets(1, scope_filter="user")
        assert len(res["global"]) == 0
        assert len(res["user"]) == 1
        assert mock_scan.call_count == 1
