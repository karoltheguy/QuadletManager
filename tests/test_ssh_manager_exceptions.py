import pytest
from unittest.mock import AsyncMock, patch
from contextlib import asynccontextmanager
from cryptography.exceptions import InvalidTag
from services.ssh_manager import (
    SSHConnectionPool,
    ServerConfigurationError,
    KeyDecryptionError,
)


@pytest.fixture
def pool():
    return SSHConnectionPool()


@pytest.fixture
def mock_db_ctx_factory():
    """Build a mock get_db_connection() context manager whose cursor.fetchone()
    returns the given row (None to simulate "server not found").
    """
    def _factory(row):
        @asynccontextmanager
        async def _mock_db():
            db_mock = AsyncMock()
            cursor_mock = AsyncMock()
            cursor_mock.fetchone.return_value = row

            @asynccontextmanager
            async def _mock_execute(*args, **kwargs):
                yield cursor_mock

            db_mock.execute = _mock_execute
            yield db_mock
        return _mock_db
    return _factory


@pytest.mark.asyncio
@pytest.mark.unit
async def test_connect_to_server_missing_row_raises_server_configuration_error(pool, mock_db_ctx_factory):
    mock_db_ctx = mock_db_ctx_factory(None)

    with patch("services.ssh_manager.get_db_connection", side_effect=mock_db_ctx):
        with pytest.raises(ServerConfigurationError) as excinfo:
            await pool.connect_to_server(42)

    assert str(excinfo.value) == "Server 42 not found or missing SSH key mapping."
    # Still catchable as a plain Exception so existing broad handlers work.
    assert isinstance(excinfo.value, Exception)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_connect_to_server_decryption_failure_raises_key_decryption_error(pool, mock_db_ctx_factory):
    mock_db_ctx = mock_db_ctx_factory(("127.0.0.1:22", "user", "enc", None))
    original_exc = InvalidTag()

    with patch("services.ssh_manager.get_db_connection", side_effect=mock_db_ctx), \
         patch("services.ssh_manager.decrypt_private_key", side_effect=original_exc):
        with pytest.raises(KeyDecryptionError) as excinfo:
            await pool.connect_to_server(7)

    assert "Failed to decrypt SSH key for server 7." in str(excinfo.value)
    assert excinfo.value.__cause__ is original_exc
    # Still catchable as a plain Exception so existing broad handlers work.
    assert isinstance(excinfo.value, Exception)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_connect_to_server_decryption_value_error_is_chained(pool, mock_db_ctx_factory):
    mock_db_ctx = mock_db_ctx_factory(("127.0.0.1:22", "user", "enc", None))
    original_exc = ValueError("bad padding")

    with patch("services.ssh_manager.get_db_connection", side_effect=mock_db_ctx), \
         patch("services.ssh_manager.decrypt_private_key", side_effect=original_exc):
        with pytest.raises(KeyDecryptionError) as excinfo:
            await pool.connect_to_server(7)

    assert excinfo.value.__cause__ is original_exc
