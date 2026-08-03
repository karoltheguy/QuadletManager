import os
import sys
import pytest
import pytest_asyncio
import aiosqlite
from unittest.mock import patch, AsyncMock, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.crypto import encrypt_private_key, decrypt_private_key, get_master_key


# ── Existing round-trip tests ─────────────────────────────────────────────────

class TestCrypto:
    def setup_method(self):
        os.environ["QUADLET_MASTER_KEY"] = "0" * 64

    def teardown_method(self):
        os.environ.pop("QUADLET_MASTER_KEY", None)

    @pytest.mark.unit
    def test_encryption_decryption_cycle(self):
        original_key = "-----BEGIN OPENSSH PRIVATE KEY-----\\nb1b2b3b4\\n-----END OPENSSH PRIVATE KEY-----" # gitleaks:allow
        encrypted = encrypt_private_key(original_key)
        assert original_key.encode('utf-8') != encrypted
        decrypted = decrypt_private_key(encrypted)
        assert original_key == decrypted


# ── Fixture: isolated DB for ensure_master_key tests ─────────────────────────

@pytest_asyncio.fixture
async def fresh_db(tmp_path):
    """Run init_db() against a temp database and restore DATABASE_PATH afterwards."""
    import core.database as db_module
    db_path = str(tmp_path / "test.db")
    original = db_module.DATABASE_PATH
    db_module.DATABASE_PATH = db_path
    try:
        await db_module.init_db()
        yield db_path
    finally:
        db_module.DATABASE_PATH = original


# ── ensure_master_key tests ───────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.unit
async def test_ensure_master_key_generates_and_persists(fresh_db):
    """When no key is configured, ensure_master_key generates a key and stores it in a
    master.key file next to the database (mode 0600) -- not in the settings table."""
    import core.database as db_module
    from core.config_loader import global_config
    original_db = db_module.DATABASE_PATH
    original_mk = global_config.master_key
    db_module.DATABASE_PATH = fresh_db
    global_config.master_key = ""
    try:
        os.environ.pop("QUADLET_MASTER_KEY", None)
        from core.crypto import ensure_master_key
        await ensure_master_key()

        assert "QUADLET_MASTER_KEY" in os.environ
        key = os.environ["QUADLET_MASTER_KEY"]
        assert len(key) == 64  # 32 bytes as hex

        key_file = os.path.join(os.path.dirname(fresh_db), "master.key")
        assert os.path.exists(key_file)
        with open(key_file, "r") as f:
            file_contents = f.read().strip()
        assert file_contents == key

        mode = os.stat(key_file).st_mode & 0o777
        assert mode == 0o600

        async with aiosqlite.connect(fresh_db) as db:
            async with db.execute("SELECT value FROM settings WHERE key = 'dev_master_key'") as cursor:
                row = await cursor.fetchone()
        assert row is None
    finally:
        db_module.DATABASE_PATH = original_db
        global_config.master_key = original_mk
        os.environ.pop("QUADLET_MASTER_KEY", None)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_ensure_master_key_reuses_persisted_key(fresh_db):
    """On second call, ensure_master_key loads the previously persisted key — not a new one."""
    import core.database as db_module
    from core.config_loader import global_config
    original_db = db_module.DATABASE_PATH
    original_mk = global_config.master_key
    db_module.DATABASE_PATH = fresh_db
    global_config.master_key = ""
    try:
        os.environ.pop("QUADLET_MASTER_KEY", None)
        from core.crypto import ensure_master_key

        await ensure_master_key()
        first_key = os.environ.pop("QUADLET_MASTER_KEY")

        await ensure_master_key()
        second_key = os.environ["QUADLET_MASTER_KEY"]

        assert first_key == second_key
    finally:
        db_module.DATABASE_PATH = original_db
        global_config.master_key = original_mk
        os.environ.pop("QUADLET_MASTER_KEY", None)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_ensure_master_key_respects_existing_env_var(fresh_db, monkeypatch):
    """If QUADLET_MASTER_KEY is already set, ensure_master_key must not overwrite it."""
    import core.database as db_module
    original_db = db_module.DATABASE_PATH
    db_module.DATABASE_PATH = fresh_db
    try:
        monkeypatch.setenv("QUADLET_MASTER_KEY", "a" * 64)
        from core.crypto import ensure_master_key
        await ensure_master_key()
        assert os.environ["QUADLET_MASTER_KEY"] == "a" * 64
    finally:
        db_module.DATABASE_PATH = original_db


@pytest.mark.asyncio
@pytest.mark.unit
async def test_ensure_master_key_idempotent_no_duplicate_rows(fresh_db):
    """Calling ensure_master_key twice must load the same key from the key file, and
    must never create a dev_master_key row in the settings table."""
    import core.database as db_module
    from core.config_loader import global_config
    original_db = db_module.DATABASE_PATH
    original_mk = global_config.master_key
    db_module.DATABASE_PATH = fresh_db
    global_config.master_key = ""
    try:
        os.environ.pop("QUADLET_MASTER_KEY", None)
        from core.crypto import ensure_master_key

        await ensure_master_key()
        first_key = os.environ.pop("QUADLET_MASTER_KEY")
        await ensure_master_key()
        second_key = os.environ["QUADLET_MASTER_KEY"]

        assert first_key == second_key

        async with aiosqlite.connect(fresh_db) as db:
            async with db.execute("SELECT COUNT(*) FROM settings WHERE key = 'dev_master_key'") as cursor:
                row = await cursor.fetchone()
        assert row[0] == 0
    finally:
        db_module.DATABASE_PATH = original_db
        global_config.master_key = original_mk
        os.environ.pop("QUADLET_MASTER_KEY", None)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_ensure_master_key_migrates_legacy_db_key(fresh_db):
    """A pre-existing dev_master_key row in the settings table must be migrated into
    the master.key file and the row removed from the DB."""
    import core.database as db_module
    from core.config_loader import global_config
    original_db = db_module.DATABASE_PATH
    original_mk = global_config.master_key
    db_module.DATABASE_PATH = fresh_db
    global_config.master_key = ""
    legacy_key = "b" * 64
    try:
        async with aiosqlite.connect(fresh_db) as db:
            await db.execute(
                "INSERT INTO settings (key, value) VALUES ('dev_master_key', ?)",
                (legacy_key,),
            )
            await db.commit()

        os.environ.pop("QUADLET_MASTER_KEY", None)
        from core.crypto import ensure_master_key
        await ensure_master_key()

        assert os.environ["QUADLET_MASTER_KEY"] == legacy_key

        key_file = os.path.join(os.path.dirname(fresh_db), "master.key")
        assert os.path.exists(key_file)
        with open(key_file, "r") as f:
            file_contents = f.read().strip()
        assert file_contents == legacy_key

        async with aiosqlite.connect(fresh_db) as db:
            async with db.execute("SELECT value FROM settings WHERE key = 'dev_master_key'") as cursor:
                row = await cursor.fetchone()
        assert row is None
    finally:
        db_module.DATABASE_PATH = original_db
        global_config.master_key = original_mk
        os.environ.pop("QUADLET_MASTER_KEY", None)


# ── SSH key decryption error surfaces a meaningful message ────────────────────

@pytest.mark.asyncio
@pytest.mark.unit
async def test_connect_to_server_decryption_failure_gives_clear_error():
    """InvalidTag from AESGCM must surface as a readable error, not an empty string."""
    from cryptography.exceptions import InvalidTag
    from services.ssh_manager import SSHConnectionPool

    test_pool = SSHConnectionPool()

    mock_cursor = AsyncMock()
    mock_cursor.fetchone = AsyncMock(return_value=("192.168.1.1", "user", b"bad_encrypted_data", None))

    class DualCM:
        async def __aenter__(self): return mock_cursor
        async def __aexit__(self, *args): return False
        def __await__(self):
            async def _r(): return mock_cursor
            return _r().__await__()

    mock_db = AsyncMock()
    mock_db.execute = MagicMock(return_value=DualCM())

    mock_db_cm = AsyncMock()
    mock_db_cm.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("services.ssh_manager.get_db_connection", return_value=mock_db_cm), \
         patch("services.ssh_manager.decrypt_private_key", side_effect=InvalidTag()):
        # connect_to_server() genuinely raises a bare Exception here (see
        # services/ssh_manager.py connect_to_server's decrypt error handling),
        # so this cannot be narrowed further.
        with pytest.raises(Exception) as exc_info:
            await test_pool.connect_to_server(1)

    error_message = str(exc_info.value)
    assert error_message  # must not be empty
    assert any(word in error_message.lower() for word in ("decrypt", "master key", "key"))

@pytest.mark.unit
def test_get_master_key_env_var(monkeypatch):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    test_key = AESGCM.generate_key(bit_length=256).hex()
    monkeypatch.setenv("QUADLET_MASTER_KEY", test_key)
    key = get_master_key()
    assert key.hex() == test_key

@pytest.mark.unit
def test_get_master_key_fallback_dev_key():
    with patch("core.config_loader.global_config") as mock_config:
        mock_config.master_key = ""
        os.environ.pop("QUADLET_MASTER_KEY", None)
        key = get_master_key()
        assert len(key) == 32
        assert "QUADLET_MASTER_KEY" in os.environ
        os.environ.pop("QUADLET_MASTER_KEY")

@pytest.mark.unit
def test_get_master_key_config_loader():
    with patch("core.config_loader.global_config") as mock_config:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        test_key = AESGCM.generate_key(bit_length=256).hex()
        mock_config.master_key = test_key
        os.environ.pop("QUADLET_MASTER_KEY", None)
        key = get_master_key()
        assert key.hex() == test_key

@pytest.mark.unit
def test_get_master_key_config_loader_hashing():
    with patch("core.config_loader.global_config") as mock_config:
        import hashlib
        mock_config.master_key = "short_key"
        os.environ.pop("QUADLET_MASTER_KEY", None)
        key = get_master_key()
        expected = hashlib.sha256(b"short_key").digest()
        assert key == expected

@pytest.mark.asyncio
@pytest.mark.unit
async def test_ensure_master_key_config_already_set():
    with patch("core.config_loader.global_config") as mock_config:
        mock_config.master_key = "config_set"
        os.environ.pop("QUADLET_MASTER_KEY", None)
        from core.crypto import ensure_master_key
        await ensure_master_key()
        assert "QUADLET_MASTER_KEY" not in os.environ
