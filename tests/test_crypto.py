import os
import unittest
from crypto import encrypt_private_key, decrypt_private_key, get_master_key

class TestCrypto(unittest.TestCase):
    def setUp(self):
        # Set a dummy master key for testing
        os.environ["QUADLET_MASTER_KEY"] = "0" * 64

    def test_encryption_decryption_cycle(self):
        original_key = "-----BEGIN OPENSSH PRIVATE KEY-----\\nb1b2b3b4\\n-----END OPENSSH PRIVATE KEY-----"
        
        # Encrypt
        encrypted = encrypt_private_key(original_key)
        self.assertNotEqual(original_key.encode('utf-8'), encrypted)
        
        # Decrypt
        decrypted = decrypt_private_key(encrypted)
        self.assertEqual(original_key, decrypted)

    def tearDown(self):
        if "QUADLET_MASTER_KEY" in os.environ:
            del os.environ["QUADLET_MASTER_KEY"]

if __name__ == "__main__":
    unittest.main()
