import asyncio
import asyncssh
import logging
from cryptography.exceptions import InvalidTag
from core.database import get_db_connection
from core.crypto import decrypt_private_key
from core.config_loader import global_config

logger = logging.getLogger("quadlet-manager.ssh")


class SSHCommandError(Exception):
    """Raised when a remote SSH command fails.

    Carries the remote exit status and stderr so callers can inspect the
    failure without parsing the message string.
    """

    def __init__(self, message: str, exit_status: int = None, stderr: str = None):
        """Initialize SSHCommandError with an error message and optional exit code/stderr."""
        super().__init__(message)
        self.exit_status = exit_status
        self.stderr = stderr


class SSHTimeoutError(SSHCommandError):
    """Raised when a remote SSH command exceeds its timeout."""


class HostKeyMismatchError(Exception):
    """Raised when a server's presented SSH host key does not match the
    previously pinned host key, or when strict host-key checking is enabled
    and no host key has been pinned yet.

    Deliberately NOT a subclass of asyncssh.DisconnectError or
    SSHCommandError so that execute_command()'s reconnect-and-retry logic
    does not treat a host-key mismatch as a transient, retryable failure.
    """


class SSHConnectionPool:
    def __init__(self):
        """Initialize the SSHConnectionPool with an empty connections dictionary."""
        # server_id -> asyncssh.SSHClientConnection
        self.connections = {}
        # server_id -> asyncio.Lock, used to serialize connection establishment
        # per server so concurrent callers don't open duplicate connections.
        self._locks: dict[int, asyncio.Lock] = {}

    def _drop_if_stale(self, server_id: int) -> bool:
        """If the cached connection for server_id has a closing/closed transport,
        pop it from self.connections and return True. Otherwise return False.

        Assumes server_id is present in self.connections.
        """
        conn = self.connections[server_id]
        # Check whether the underlying transport is still open.
        # asyncssh's SSHClientConnection wraps an asyncio Transport;
        # if the transport is closing/closed the connection is stale.
        transport = getattr(conn, '_transport', None)
        if transport is None or transport.is_closing():
            logger.info(f"Cached SSH connection for server {server_id} has a closed transport – dropping.")
            self.connections.pop(server_id, None)
            return True
        return False

    async def get_connection(self, server_id: int):
        if server_id in self.connections:
            if not self._drop_if_stale(server_id):
                return self.connections[server_id]

        # No live cached connection here means we need to connect. Serialize
        # via a per-server lock so concurrent callers don't each open their
        # own connection (setdefault has no await point, so it's safe to
        # call without an extra guard lock).
        lock = self._locks.setdefault(server_id, asyncio.Lock())
        async with lock:
            # Re-check under the lock: another coroutine may have already
            # connected and populated self.connections while we were waiting
            # for the lock. That connection could have died since it was
            # established/confirmed, so re-run the staleness check before
            # reusing it.
            if server_id in self.connections:
                if not self._drop_if_stale(server_id):
                    return self.connections[server_id]

            return await self.connect_to_server(server_id)

    async def connect_to_server(self, server_id: int):
        logger.info(f"Establishing new SSH connection to server {server_id}")
        async with get_db_connection() as db:
            async with db.execute("""
                SELECT s.ip_address, s.ssh_user, k.encrypted_private_key, s.host_key
                FROM servers s JOIN ssh_keys k ON s.ssh_key_id = k.id
                WHERE s.id = ?
            """, (server_id,)) as cursor:
                row = await cursor.fetchone()
            if not row:
                raise Exception(f"Server {server_id} not found or missing SSH key mapping.")

            ip_address, ssh_user, encrypted_pk, stored_host_key = row

        # DB context is closed here, deliberately, before any network I/O so
        # the SSH handshake (which can be slow/blocking on a bad network)
        # doesn't hold a database connection open.

        host = ip_address
        port = 22
        if ':' in host:
            parts = host.split(':', 1)
            host = parts[0]
            port = int(parts[1])

        # Decrypt the key in memory
        try:
            private_key_str = decrypt_private_key(encrypted_pk)
        except (InvalidTag, ValueError) as exc:
            raise Exception(
                f"Failed to decrypt SSH key for server {server_id}. "
                "The master key may have changed since this server was configured. "
                "Set QUADLET_MASTER_KEY to a stable value and re-add the server if needed."
            ) from exc

        # Load key for asyncssh
        key = asyncssh.import_private_key(private_key_str)

        remediation_hint = (
            "If the server was legitimately rekeyed, use 'Re-pin host key' "
            "in Settings > Servers."
        )

        if stored_host_key:
            # Verify the presented host key against the pinned key.
            pinned = asyncssh.import_public_key(stored_host_key)
            known_hosts_arg = ([pinned], [], [])
        elif global_config.ssh_strict_host_keys:
            # Strict mode with no pinned key: refuse to connect blindly.
            raise HostKeyMismatchError(
                f"Server {server_id} has no pinned host key and strict host "
                "key checking is enabled. Pin the key via the re-pin action "
                "or provision it out of band before connecting."
            )
        else:
            # TOFU: trust the presented key on first connect and pin it below.
            known_hosts_arg = None

        try:
            conn = await asyncssh.connect(
                host=host,
                port=port,
                username=ssh_user,
                client_keys=[key],
                known_hosts=known_hosts_arg,
            )
        except asyncssh.HostKeyNotVerifiable as exc:
            raise HostKeyMismatchError(
                f"Host key verification failed for server {server_id}: the "
                "presented SSH host key does not match the pinned host key. "
                f"{remediation_hint}"
            ) from exc

        if not stored_host_key:
            # TOFU: trust the presented key on first connect and pin it.
            host_key_obj = conn.get_server_host_key()
            if host_key_obj is not None:
                exported = host_key_obj.export_public_key()
                if isinstance(exported, bytes):
                    exported = exported.decode()
                async with get_db_connection() as pin_db:
                    await pin_db.execute(
                        "UPDATE servers SET host_key = ? WHERE id = ?",
                        (exported, server_id),
                    )
                    await pin_db.commit()

        self.connections[server_id] = conn
        return conn

    async def _run_with_timeout(self, conn, command: str, timeout: float, server_id: int) -> str:
        """Run a command on the given connection with proper timeout handling.

        Uses create_process() so we get a handle to explicitly kill the remote
        process when the local timeout fires, preventing orphaned processes from
        piling up and locking the podman database on the server.
        """
        process = await conn.create_process(command)
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout
            )
            if process.exit_status and process.exit_status != 0:
                raise asyncssh.ProcessError(
                    env=None, command=command,
                    subsystem=None, exit_status=process.exit_status,
                    exit_signal=None, returncode=process.exit_status,
                    stdout=stdout or '', stderr=stderr or ''
                )
            return stdout or ""
        except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
            # Kill the remote process regardless of whether we're timing out or
            # being cancelled (e.g. app shutdown via Ctrl+C).  Without this,
            # CancelledError would bypass the cleanup block entirely, leaving
            # the SSH channel open and making uvicorn loop on shutdown.
            try:
                process.kill()
            except Exception as cleanup_exc:
                logger.debug(f"Failed to kill remote process on server {server_id}: {cleanup_exc}")
            try:
                process.close()
            except Exception as cleanup_exc:
                logger.debug(f"Failed to close remote process on server {server_id}: {cleanup_exc}")
            if isinstance(exc, asyncio.CancelledError):
                raise  # Let cancellation propagate normally so shutdown works
            logger.error(f"Command '{command}' timed out after {timeout}s on server {server_id}")
            raise SSHTimeoutError(f"Command timed out after {timeout}s: {command}") from exc

    async def _reconnect_and_retry(self, server_id: int, command: str, timeout: float, reason: str) -> str:
        """Drop the cached connection, reconnect, and retry the command once."""
        logger.warning(f"{reason} for server {server_id}. Reconnecting...")
        old_conn = self.connections.pop(server_id, None)
        if old_conn:
            try:
                old_conn.close()
            except Exception as close_exc:
                logger.debug(f"Failed to close stale connection for server {server_id}: {close_exc}")
        conn = await self.get_connection(server_id)
        return await self._run_with_timeout(conn, command, timeout, server_id)

    async def execute_command(self, server_id: int, command: str, use_sudo: bool = False, timeout: float = 30.0) -> str:
        """Execute a command, prepending sudo if requested.

        :param server_id: The server ID.
        :param command: The command to execute on the remote host.
        :param use_sudo: When True, prepends 'sudo' to the command. Defaults to False.
        :param timeout: Maximum seconds to wait for the command to complete. Defaults to 30.0.
        :return: The stdout of the command on success.
        """
        if use_sudo:
            command = f"sudo {command}"
            
        conn = await self.get_connection(server_id)
        try:
            return await self._run_with_timeout(conn, command, timeout, server_id)
        except asyncssh.ProcessError as exc:
            logger.exception(f"Command '{command}' failed on server {server_id}: {exc.stderr}")
            raise SSHCommandError(
                f"Command execution failed: {exc.stderr}",
                exit_status=exc.exit_status, stderr=exc.stderr
            ) from exc
        except asyncssh.ChannelOpenError:
            # The SSH connection is alive at the TCP level but the server
            # refused to open a new session channel (e.g. stale connection,
            # server channel limit reached).  Reconnect and retry once.
            return await self._reconnect_and_retry(
                server_id, command, timeout, "Channel open failed"
            )
        except (asyncssh.ConnectionLost, asyncssh.DisconnectError):
            # Connection dropped — reconnect once and retry
            return await self._reconnect_and_retry(
                server_id, command, timeout, "Connection lost"
            )

    async def close_all(self):
        for conn in self.connections.values():
            conn.close()
        self.connections.clear()

# Global singleton
pool = SSHConnectionPool()
