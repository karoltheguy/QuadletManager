import os
import secrets
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Master key must be securely provided via environment variables.
# For AES-256 it should be 32 bytes (256 bits).
def get_master_key() -> bytes:
    key_hex = os.getenv("QUADLET_MASTER_KEY")
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
