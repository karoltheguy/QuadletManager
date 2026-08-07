import asyncio
import os
import logging
import secrets
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger("quadlet-manager.crypto")

# Master key must be securely provided via environment variables.
# For AES-256 it should be 32 bytes (256 bits).
def get_master_key() -> bytes:
    from core.config_loader import global_config
    key_hex = os.getenv("QUADLET_MASTER_KEY")
    if not key_hex and getattr(global_config, "master_key", ""):
        key_hex = global_config.master_key
        # Check if the length is a valid hex encoded 256-bit key (64 characters)
        if len(key_hex) != 64:
            # Hash it if it's not a proper 256-bit hex key to ensure it works
            import hashlib
            key_hex = hashlib.sha256(key_hex.encode()).hexdigest()
            print("WARNING: Configured master_key is not an explicit 64-char hex string, hashing it.")
            
    if not key_hex:
        # For development purposes ONLY. In production, fail if missing.
        print("WARNING: Quadlet Manager Master Key not found in Env! Using volatile dev key.")
        dev_key = AESGCM.generate_key(bit_length=256)
        os.environ["QUADLET_MASTER_KEY"] = dev_key.hex()
        return dev_key
    
    return bytes.fromhex(key_hex)

def encrypt_private_key(private_key: str) -> bytes:
    """Encrypts an SSH private key using AES-256-GCM."""
    master_key = get_master_key()
    aesgcm = AESGCM(master_key)
    
    # 12-byte (96-bit) nonce is standard for AES-GCM
    nonce = secrets.token_bytes(12)
    
    # Encrypt the private key string (converted to bytes)
    ciphertext = aesgcm.encrypt(nonce, private_key.encode('utf-8'), None)
    
    # Prepend the nonce to the ciphertext for storage
    return nonce + ciphertext

def _write_key_file(path: str, key: str) -> None:
    """Write `key` to a new file at `path` with 0600 permissions.

    The file must not already exist (created with O_EXCL). If `os.fdopen`
    fails to wrap the raw descriptor, the descriptor is closed manually;
    once `os.fdopen` succeeds, the returned file object (used as a context
    manager) owns the descriptor and is responsible for closing it.
    """
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        f = os.fdopen(fd, "w")
    except Exception:
        os.close(fd)
        raise
    with f:
        f.write(key)


async def ensure_master_key() -> None:
    """Ensure a stable master key is available before any SSH operations run.

    If QUADLET_MASTER_KEY or config master_key is already set, this is a no-op.
    Otherwise a dev key is loaded from (or persisted to) a `master.key` file
    (mode 0600) in the database directory, so the same key survives
    application restarts. Any legacy dev key found in the `settings` table
    is migrated to that file and removed from the table. Call this once at
    startup after init_db().
    """
    from core.config_loader import global_config
    from core.database import get_db_connection
    import core.database as db_module

    if os.getenv("QUADLET_MASTER_KEY"):
        return
    if getattr(global_config, "master_key", ""):
        return

    key_file = os.path.join(os.path.dirname(os.path.abspath(db_module.DATABASE_PATH)), "master.key")

    if os.path.exists(key_file):
        # to_thread rather than a plain open(): this function is async, and a
        # synchronous read blocks the event loop.
        key = (await asyncio.to_thread(
            Path(key_file).read_text, encoding="utf-8"
        )).strip()
        os.environ["QUADLET_MASTER_KEY"] = key
        logger.warning(
            "QUADLET_MASTER_KEY not set; loaded persisted dev key from %s. "
            "Set QUADLET_MASTER_KEY to a stable 64-char hex value for production.",
            key_file,
        )
        return

    async with get_db_connection() as db:
        async with db.execute("SELECT value FROM settings WHERE key = 'dev_master_key'") as cursor:
            row = await cursor.fetchone()

        if row:
            key = row[0]
            _write_key_file(key_file, key)
            await db.execute("DELETE FROM settings WHERE key = 'dev_master_key'")
            await db.commit()
            os.environ["QUADLET_MASTER_KEY"] = key
            logger.warning(
                "QUADLET_MASTER_KEY not set; migrated legacy dev key from the database to %s. "
                "Set QUADLET_MASTER_KEY to a stable 64-char hex value for production.",
                key_file,
            )
        else:
            new_key = AESGCM.generate_key(bit_length=256).hex()
            _write_key_file(key_file, new_key)
            os.environ["QUADLET_MASTER_KEY"] = new_key
            logger.warning(
                "QUADLET_MASTER_KEY not set; generated a dev key and persisted it to %s. "
                "This is NOT secure for production. Set QUADLET_MASTER_KEY to a stable 64-char hex value.",
                key_file,
            )


def decrypt_private_key(encrypted_data: bytes) -> str:
    """Decrypts an SSH private key using AES-256-GCM."""
    master_key = get_master_key()
    aesgcm = AESGCM(master_key)
    
    # Extract the 12-byte nonce
    nonce = encrypted_data[:12]
    ciphertext = encrypted_data[12:]
    
    # Decrypt and return the original string
    decrypted_bytes = aesgcm.decrypt(nonce, ciphertext, None)
    return decrypted_bytes.decode('utf-8')
