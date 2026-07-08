import pytest
from unittest.mock import AsyncMock, patch

from services.remote_fs import (
    GLOBAL_QUADLET_DIR,
    is_global_scope,
    quadlet_dir_for_scope,
    remote_home_dir,
    write_remote_file,
)


@pytest.fixture
def mock_pool():
    with patch("services.remote_fs.pool") as m:
        m.execute_command = AsyncMock()
        yield m


@pytest.mark.unit
def test_is_global_scope():
    assert is_global_scope("global") is True
    assert is_global_scope("user") is False


@pytest.mark.asyncio
@pytest.mark.unit
async def test_remote_home_dir_strips_output(mock_pool):
    mock_pool.execute_command.return_value = "/home/alice\n"
    assert await remote_home_dir(1) == "/home/alice"
    cmd = mock_pool.execute_command.call_args[0][1]
    assert "$HOME" in cmd


@pytest.mark.asyncio
@pytest.mark.unit
async def test_remote_home_dir_rejects_non_absolute(mock_pool):
    mock_pool.execute_command.return_value = ""
    with pytest.raises(ValueError):
        await remote_home_dir(1)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_quadlet_dir_for_scope_global_needs_no_ssh(mock_pool):
    assert await quadlet_dir_for_scope(1, "global") == GLOBAL_QUADLET_DIR
    mock_pool.execute_command.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.unit
async def test_quadlet_dir_for_scope_user_is_absolute(mock_pool):
    mock_pool.execute_command.return_value = "/home/alice\n"
    path = await quadlet_dir_for_scope(1, "user")
    assert path == "/home/alice/.config/containers/systemd"
    assert "~" not in path


@pytest.mark.asyncio
@pytest.mark.unit
async def test_write_remote_file_quotes_path_and_content(mock_pool):
    await write_remote_file(1, "/etc/containers/systemd/a b.container", "[Container]\n", use_sudo=True)
    cmd = mock_pool.execute_command.call_args[0][1]
    assert "sudo tee '/etc/containers/systemd/a b.container'" in cmd
    assert cmd.startswith("printf '%s' ")
    assert mock_pool.execute_command.call_args[1]["use_sudo"] is False


@pytest.mark.asyncio
@pytest.mark.unit
async def test_write_remote_file_without_sudo(mock_pool):
    await write_remote_file(1, "/home/alice/.config/containers/systemd/x.container", "data", use_sudo=False)
    cmd = mock_pool.execute_command.call_args[0][1]
    assert "sudo" not in cmd
    assert "tee /home/alice/.config/containers/systemd/x.container" in cmd
