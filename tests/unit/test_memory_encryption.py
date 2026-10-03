"""Unit tests for Memory Encryption and fail-closed key loading."""

from __future__ import annotations

import unittest
from cryptography.fernet import Fernet

from app.core.config import BuddyConfig
from app.core.exceptions import MemoryEncryptionError
from app.memory.encryption import (
    FernetMemoryEncryptor,
    NoOpMemoryEncryptor,
    derive_key_from_passphrase,
    get_memory_encryptor,
)
from app.memory.models import MemoryRecord
from app.memory.store import SqliteMemoryStore


class TestMemoryEncryption(unittest.TestCase):
    """Test Fernet encrypt/decrypt cycle, fail-closed missing key behavior, and encrypted DB storage."""

    def test_fernet_encrypt_decrypt_cycle(self) -> None:
        key = Fernet.generate_key()
        encryptor = FernetMemoryEncryptor(key)

        original = "User lives in New York City"
        ciphertext = encryptor.encrypt(original)
        self.assertNotEqual(original, ciphertext)
        self.assertTrue(len(ciphertext) > len(original))

        decrypted = encryptor.decrypt(ciphertext)
        self.assertEqual(decrypted, original)

    def test_corrupt_ciphertext_raises_error(self) -> None:
        key = Fernet.generate_key()
        encryptor = FernetMemoryEncryptor(key)

        with self.assertRaises(MemoryEncryptionError):
            encryptor.decrypt("invalid_corrupt_base64_string")

    def test_fail_closed_when_key_missing_and_encryption_enabled(self) -> None:
        config = BuddyConfig(
            memory_encryption_enabled=True,
            memory_encryption_key=None,
        )
        with self.assertRaises(MemoryEncryptionError):
            get_memory_encryptor(config)

    def test_encrypted_sqlite_storage(self) -> None:
        key = Fernet.generate_key()
        encryptor = FernetMemoryEncryptor(key)
        store = SqliteMemoryStore(db_path=":memory:", encryptor=encryptor)
        try:
            rec = MemoryRecord(content="Secret user fact")
            store.save(rec)

            # Raw SQLite row should contain ciphertext, not plaintext
            cursor = store._conn.cursor()
            cursor.execute("SELECT content FROM memory_records WHERE memory_id = ?;", (rec.memory_id,))
            raw_content = cursor.fetchone()[0]
            self.assertNotEqual(raw_content, "Secret user fact")

            # Decrypted read through store.get() returns plaintext
            retrieved = store.get(rec.memory_id)
            assert retrieved is not None
            self.assertEqual(retrieved.content, "Secret user fact")
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
