import asyncio
import asyncssh
import logging
from core.database import get_db_connection
from core.crypto import decrypt_private_key

logger = logging.getLogger("quadlet-manager.ssh")

class SSHConnectionPool:
    def __init__(self):
        # server_id -> asyncssh.SSHClientConnection
        self.connections = {}

    async def get_connection(self, server_id: int):
        if server_id in self.connections:
            # Check if connection is still active; if so return it.
            # Otherwise we'll drop it and reconnect.
            conn = self.connections[server_id]
            # asyncssh doesn't have an explicit is_active without trying a keepalive 
            # or checking if writer is closing, but we'll try a basic ping or catch exceptions on use.
            return conn
            
        return await self.connect_to_server(server_id)

    async def connect_to_server(self, server_id: int):
        conn = None
        logger.info(f"Establishing new SSH connection to server {server_id}")
        async with await get_db_connection() as db:
            async with db.execute("""
                SELECT s.ip_address, s.ssh_user, k.encrypted_private_key 
                FROM servers s JOIN ssh_keys k ON s.ssh_key_id = k.id 
                WHERE s.id = ?
            """, (server_id,)) as cursor:
                row = await cursor.fetchone()
                if not row:
                    raise Exception(f"Server {server_id} not found or missing SSH key mapping.")
                
                ip_address, ssh_user, encrypted_pk = row
                
                # Decrypt the key in memory
                private_key_str = decrypt_private_key(encrypted_pk)
                
                # Load key for asyncssh
                key = asyncssh.import_private_key(private_key_str)
                
                # Create connection
                conn = await asyncssh.connect(
                    host=ip_address, 
                    username=ssh_user, 
                    client_keys=[key],
                    known_hosts=None  # Can be expanded to verify known_hosts but left None for dev
                )
                
                self.connections[server_id] = conn
                return conn

    async def execute_command(self, server_id: int, command: str, use_sudo: bool = False) -> str:
        """Executes a command. Prepends sudo if requested."""
        if use_sudo:
            command = f"sudo {command}"
            
        conn = await self.get_connection(server_id)
        try:
            result = await conn.run(command, check=True)
            return result.stdout or ""
        except asyncssh.ProcessError as exc:
            logger.error(f"Command '{command}' failed on server {server_id}: {exc.stderr}")
            raise Exception(f"Command execution failed: {exc.stderr}")
        except asyncssh.ConnectionLost:
            # Reconnect once and retry
            logger.warning(f"Connection lost for server {server_id}. Reconnecting...")
            self.connections.pop(server_id, None)
            conn = await self.get_connection(server_id)
            result = await conn.run(command, check=True)
            return result.stdout or ""

    async def close_all(self):
        for conn in self.connections.values():
            conn.close()
        self.connections.clear()

# Global singleton
pool = SSHConnectionPool()
