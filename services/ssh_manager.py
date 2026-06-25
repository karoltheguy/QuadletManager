import asyncio
import asyncssh
import logging
from cryptography.exceptions import InvalidTag
from core.database import get_db_connection
from core.crypto import decrypt_private_key

logger = logging.getLogger("quadlet-manager.ssh")

class SSHConnectionPool:
    def __init__(self):
        # server_id -> asyncssh.SSHClientConnection
        self.connections = {}

    async def get_connection(self, server_id: int):
        if server_id in self.connections:
            conn = self.connections[server_id]
            # Check whether the underlying transport is still open.
            # asyncssh's SSHClientConnection wraps an asyncio Transport;
            # if the transport is closing/closed the connection is stale.
            transport = getattr(conn, '_transport', None)
            if transport is None or transport.is_closing():
                logger.info(f"Cached SSH connection for server {server_id} has a closed transport – dropping.")
                self.connections.pop(server_id, None)
            else:
                return conn

        return await self.connect_to_server(server_id)

    async def connect_to_server(self, server_id: int):
        conn = None
        logger.info(f"Establishing new SSH connection to server {server_id}")
        async with get_db_connection() as db:
            async with db.execute("""
                SELECT s.ip_address, s.ssh_user, k.encrypted_private_key 
                FROM servers s JOIN ssh_keys k ON s.ssh_key_id = k.id 
                WHERE s.id = ?
            """, (server_id,)) as cursor:
                row = await cursor.fetchone()
                if not row:
                    raise Exception(f"Server {server_id} not found or missing SSH key mapping.")
                
                ip_address, ssh_user, encrypted_pk = row
                
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
                
                # Create connection
                conn = await asyncssh.connect(
                    host=host,
                    port=port,
                    username=ssh_user, 
                    client_keys=[key],
                    known_hosts=None  # Can be expanded to verify known_hosts but left None for dev
                )
                
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
            except Exception:
                pass
            try:
                process.close()
            except Exception:
                pass
            if isinstance(exc, asyncio.CancelledError):
                raise  # Let cancellation propagate normally so shutdown works
            logger.error(f"Command '{command}' timed out after {timeout}s on server {server_id}")
            raise Exception(f"Command timed out after {timeout}s: {command}")

    async def _reconnect_and_retry(self, server_id: int, command: str, timeout: float, reason: str) -> str:
        """Drop the cached connection, reconnect, and retry the command once."""
        logger.warning(f"{reason} for server {server_id}. Reconnecting...")
        old_conn = self.connections.pop(server_id, None)
        if old_conn:
            try:
                old_conn.close()
            except Exception:
                pass
        conn = await self.get_connection(server_id)
        return await self._run_with_timeout(conn, command, timeout, server_id)

    async def execute_command(self, server_id: int, command: str, use_sudo: bool = False, timeout: float = 30.0) -> str:
        """Executes a command. Prepends sudo if requested.
        
        Args:
            timeout: Maximum seconds to wait for the command to complete.
                     Defaults to 30s. Set to None to wait indefinitely (not recommended).
        """
        if use_sudo:
            command = f"sudo {command}"
            
        conn = await self.get_connection(server_id)
        try:
            return await self._run_with_timeout(conn, command, timeout, server_id)
        except asyncssh.ProcessError as exc:
            logger.error(f"Command '{command}' failed on server {server_id}: {exc.stderr}")
            raise Exception(f"Command execution failed: {exc.stderr}")
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
