"""RED-phase tests for issue #166: SSH host-key verification / TOFU pinning.

These tests assert a contract that does not exist yet:
- services.ssh_manager.HostKeyMismatchError
- TOFU pinning of servers.host_key on first connect
- verification against a pinned host_key on subsequent connects
- core.config_loader.AppConfig.ssh_strict_host_keys
- POST /api/settings/servers/{server_id}/repin-host-key admin endpoint
- servers.host_key column created by core.database.init_db()

All imports of not-yet-existing symbols are done inside the test functions so
that a missing symbol only fails that one test, not the whole module's
collection.
"""
import os
import sys
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import asyncssh
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def _mock_db_ctx(fetchone_result):
    """Build an async-context-manager-based fake DB matching ssh_manager's usage:

    async with get_db_connection() as db:
        async with db.execute(...) as cursor:
            row = await cursor.fetchone()
        await db.execute(...)   # plain awaited execute, e.g. for UPDATE
        await db.commit()
    """
    # SELECT is used as `async with db.execute(...) as cursor:`
    # UPDATE/other writes are used as plain `await db.execute(...)`.
    # We support both by making execute() return an object that is both
    # awaitable and an async context manager, and we record every call so
    # tests can assert on the SQL/params used for writes.
    class _DualExecute:
        def __init__(self, cursor):
            self._cursor = cursor
            self.calls = []

        def __call__(self, sql, params=None):
            self.calls.append((sql, params))
            return self

        async def __aenter__(self):
            return self._cursor

        async def __aexit__(self, *a):
            return False

        def __await__(self):
            async def _noop():
                return None
            return _noop().__await__()

    @asynccontextmanager
    async def _ctx():
        cursor_mock = AsyncMock()
        cursor_mock.fetchone.return_value = fetchone_result

        db_mock = MagicMock()
        db_mock.execute = _DualExecute(cursor_mock)
        db_mock.commit = AsyncMock()
        _ctx.last_execute = db_mock.execute
        yield db_mock

    return _ctx


@pytest.mark.asyncio
@pytest.mark.unit
async def test_tofu_pins_host_key_on_first_connect():
    """No stored host_key, strict mode off: connect_to_server() should pin the
    server's host key by writing get_server_host_key().export_public_key() into
    servers.host_key.
    """
    from services.ssh_manager import SSHConnectionPool

    pool = SSHConnectionPool()
    # row: ip_address, ssh_user, encrypted_private_key, host_key (None = unpinned)
    db_ctx = _mock_db_ctx(("127.0.0.1:22", "user", "enc", None))

    exported = b'ssh-ed25519 AAAA... pinned'
    mock_host_key = MagicMock()
    mock_host_key.export_public_key.return_value = exported

    mock_conn = MagicMock()
    mock_conn.get_server_host_key.return_value = mock_host_key

    with patch("services.ssh_manager.get_db_connection", side_effect=db_ctx), \
         patch("asyncssh.connect", new_callable=AsyncMock) as mock_connect, \
         patch("services.ssh_manager.decrypt_private_key", return_value="dummy_key"), \
         patch("asyncssh.import_private_key"):

        mock_connect.return_value = mock_conn

        await pool.connect_to_server(1)

        mock_connect.assert_called_once()
        mock_conn.get_server_host_key.assert_called_once()

        # Assert a DB write persisted the exported key, decoded to a str
        # (the host_key column is TEXT, and export_public_key() returns bytes).
        expected = exported.decode()
        executed = db_ctx.last_execute.calls
        matching = [
            (sql, params) for sql, params in executed
            if "host_key" in sql.lower() and params and expected in params
        ]
        assert matching, f"Expected a write persisting {expected!r} to host_key; got calls: {executed}"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_tofu_no_persist_when_host_key_is_none():
    """If get_server_host_key() returns None, no persist and no error."""
    from services.ssh_manager import SSHConnectionPool

    pool = SSHConnectionPool()
    db_ctx = _mock_db_ctx(("127.0.0.1:22", "user", "enc", None))

    mock_conn = MagicMock()
    mock_conn.get_server_host_key.return_value = None

    with patch("services.ssh_manager.get_db_connection", side_effect=db_ctx), \
         patch("asyncssh.connect", new_callable=AsyncMock) as mock_connect, \
         patch("services.ssh_manager.decrypt_private_key", return_value="dummy_key"), \
         patch("asyncssh.import_private_key"):

        mock_connect.return_value = mock_conn

        # Should not raise.
        result = await pool.connect_to_server(1)
        assert result is mock_conn


@pytest.mark.asyncio
@pytest.mark.unit
async def test_verify_pinned_host_key_passed_to_connect():
    """A stored host_key must be used to build known_hosts=(keys, [], []) for
    asyncssh.connect(), rather than known_hosts=None.
    """
    from services.ssh_manager import SSHConnectionPool

    pool = SSHConnectionPool()
    stored_pubkey = b'ssh-ed25519 AAAA... stored'
    db_ctx = _mock_db_ctx(("127.0.0.1:22", "user", "enc", stored_pubkey))

    imported_marker = MagicMock(name="imported_pinned_key")

    with patch("services.ssh_manager.get_db_connection", side_effect=db_ctx), \
         patch("asyncssh.connect", new_callable=AsyncMock) as mock_connect, \
         patch("services.ssh_manager.decrypt_private_key", return_value="dummy_key"), \
         patch("asyncssh.import_private_key"), \
         patch("asyncssh.import_public_key", return_value=imported_marker) as mock_import_pub:

        mock_connect.return_value = MagicMock()

        await pool.connect_to_server(1)

        mock_import_pub.assert_called_once()
        _, kwargs = mock_connect.call_args
        known_hosts = kwargs.get("known_hosts")
        assert known_hosts is not None, "known_hosts must not be None when a host_key is pinned"
        assert known_hosts[0] == [imported_marker]
        assert known_hosts[1] == []
        assert known_hosts[2] == []


@pytest.mark.asyncio
@pytest.mark.unit
async def test_host_key_mismatch_raises_fatal_error_not_retried():
    """asyncssh.HostKeyNotVerifiable during connect must surface as
    services.ssh_manager.HostKeyMismatchError, which must NOT be a
    asyncssh.DisconnectError subclass (so it isn't treated as retryable),
    and execute_command() must propagate it without a second connect attempt.
    """
    from services.ssh_manager import HostKeyMismatchError, SSHConnectionPool

    assert not issubclass(HostKeyMismatchError, asyncssh.DisconnectError)

    pool = SSHConnectionPool()
    stored_pubkey = b'ssh-ed25519 AAAA... stored'
    db_ctx = _mock_db_ctx(("127.0.0.1:22", "user", "enc", stored_pubkey))

    with patch("services.ssh_manager.get_db_connection", side_effect=db_ctx), \
         patch("asyncssh.connect", new_callable=AsyncMock,
               side_effect=asyncssh.HostKeyNotVerifiable("mismatch", "en-US")), \
         patch("services.ssh_manager.decrypt_private_key", return_value="dummy_key"), \
         patch("asyncssh.import_private_key"), \
         patch("asyncssh.import_public_key"):

        with pytest.raises(HostKeyMismatchError):
            await pool.connect_to_server(1)

    # execute_command must not retry on this error: patch get_connection to
    # raise HostKeyMismatchError and assert connect_to_server (used by the
    # reconnect path) is never invoked a second time.
    with patch.object(pool, "get_connection", new_callable=AsyncMock,
                       side_effect=HostKeyMismatchError("mismatch")), \
         patch.object(pool, "connect_to_server", new_callable=AsyncMock) as mock_reconnect:
        with pytest.raises(HostKeyMismatchError):
            await pool.execute_command(1, "ls")
        mock_reconnect.assert_not_called()


@pytest.mark.unit
def test_app_config_ssh_strict_host_keys_default_and_yaml_override():
    """AppConfig.ssh_strict_host_keys defaults to False and is settable via
    yaml data through _apply_config_data()."""
    from core.config_loader import AppConfig

    config = AppConfig.__new__(AppConfig)
    config.ssh_strict_host_keys = False  # simulate default init without triggering yaml load
    assert config.ssh_strict_host_keys is False

    config._apply_config_data({"ssh_strict_host_keys": True})
    assert config.ssh_strict_host_keys is True


@pytest.mark.asyncio
@pytest.mark.unit
async def test_strict_mode_refuses_unpinned_host_without_connecting():
    """When ssh_strict_host_keys is True and no host_key is pinned yet,
    connect_to_server() must raise before ever calling asyncssh.connect()."""
    from services.ssh_manager import SSHConnectionPool
    import services.ssh_manager as ssh_manager_module

    pool = SSHConnectionPool()
    db_ctx = _mock_db_ctx(("127.0.0.1:22", "user", "enc", None))

    with patch("services.ssh_manager.get_db_connection", side_effect=db_ctx), \
         patch("asyncssh.connect", new_callable=AsyncMock) as mock_connect, \
         patch("services.ssh_manager.decrypt_private_key", return_value="dummy_key"), \
         patch("asyncssh.import_private_key"), \
         patch.object(ssh_manager_module, "global_config", MagicMock(ssh_strict_host_keys=True)):

        with pytest.raises(Exception):
            await pool.connect_to_server(1)

        mock_connect.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.unit
async def test_repin_endpoint_requires_admin():
    from api.routes import settings_repin_server_host_key

    with pytest.raises(Exception) as exc_info:
        await settings_repin_server_host_key(
            request=MagicMock(),
            server_id=1,
            role="viewer",
            is_admin=False,
        )
    assert getattr(exc_info.value, "status_code", None) == 403


@pytest.mark.asyncio
@pytest.mark.unit
async def test_repin_endpoint_clears_stored_key_and_pool_entry_for_admin():
    from api.routes import settings_repin_server_host_key, pool

    pool.connections[1] = MagicMock()

    class _DualExecute:
        """Supports both `await db.execute(...)` (used for the UPDATE here)
        and `async with db.execute(...) as cursor:` (used by
        settings_list_servers, which this handler calls to build its
        response), recording every call for assertions.
        """

        def __init__(self, cursor):
            self._cursor = cursor
            self.calls = []

        def __call__(self, sql, params=None):
            self.calls.append((sql, params))
            return self

        async def __aenter__(self):
            return self._cursor

        async def __aexit__(self, *a):
            return False

        def __await__(self):
            async def _noop():
                return None
            return _noop().__await__()

    cursor_mock = AsyncMock()
    cursor_mock.fetchall.return_value = []

    conn_mock = MagicMock()
    conn_mock.execute = _DualExecute(cursor_mock)
    conn_mock.commit = AsyncMock()

    db_ctx_mgr = MagicMock()
    db_ctx_mgr.__aenter__ = AsyncMock(return_value=conn_mock)
    db_ctx_mgr.__aexit__ = AsyncMock(return_value=False)

    with patch("api.routes.get_db_connection", return_value=db_ctx_mgr):
        response = await settings_repin_server_host_key(
            request=MagicMock(),
            server_id=1,
            role="editor",
            is_admin=True,
        )

    assert getattr(response, "status_code", 200) == 200
    assert 1 not in pool.connections

    executed_sql = " ".join(str(sql) for sql, _params in conn_mock.execute.calls)
    assert "host_key" in executed_sql
    assert "NULL" in executed_sql.upper()


@pytest.mark.asyncio
@pytest.mark.unit
async def test_init_db_creates_host_key_column(tmp_path):
    import core.database as db_module

    db_path = str(tmp_path / "test_host_key_pinning.db")
    original = db_module.DATABASE_PATH
    db_module.DATABASE_PATH = db_path
    try:
        await db_module.init_db()

        import aiosqlite
        async with aiosqlite.connect(db_path) as db:
            async with db.execute("PRAGMA table_info(servers)") as cursor:
                cols = [row[1] async for row in cursor]
        assert "host_key" in cols
    finally:
        db_module.DATABASE_PATH = original
