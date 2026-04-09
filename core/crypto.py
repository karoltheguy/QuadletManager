import os
import logging
import secrets
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

async def ensure_master_key() -> None:
    """Ensure a stable master key is available before any SSH operations run.

    If QUADLET_MASTER_KEY or config master_key is already set, this is a no-op.
    Otherwise a dev key is loaded from (or persisted to) the `settings` table so
    the same key survives application restarts.  Call this once at startup after
    init_db().
    """
    from core.config_loader import global_config
    from core.database import get_db_connection

    if os.getenv("QUADLET_MASTER_KEY"):
        return
    if getattr(global_config, "master_key", ""):
        return

    async with get_db_connection() as db:
        async with db.execute("SELECT value FROM settings WHERE key = 'dev_master_key'") as cursor:
            row = await cursor.fetchone()

        if row:
            os.environ["QUADLET_MASTER_KEY"] = row[0]
            logger.warning(
                "QUADLET_MASTER_KEY not set; loaded persisted dev key from database. "
                "Set QUADLET_MASTER_KEY to a stable 64-char hex value for production."
            )
        else:
            new_key = AESGCM.generate_key(bit_length=256).hex()
            await db.execute(
                "INSERT INTO settings (key, value) VALUES ('dev_master_key', ?)",
                (new_key,),
            )
            await db.commit()
            os.environ["QUADLET_MASTER_KEY"] = new_key
            logger.warning(
                "QUADLET_MASTER_KEY not set; generated and persisted a dev key to the database. "
                "This is NOT secure for production. Set QUADLET_MASTER_KEY to a stable 64-char hex value."
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
