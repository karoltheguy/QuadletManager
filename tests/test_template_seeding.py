"""Tests for default template seeding (issue #30).

Verifies that Volume, Network, and Pod templates are seeded alongside
the existing Container template in init_db().
"""
import sys
import os
import pytest
import pytest_asyncio
import aiosqlite

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


@pytest_asyncio.fixture
async def fresh_db(tmp_path):
    """Run init_db() against a temporary database and return the path."""
    import core.database as db_module
    db_path = str(tmp_path / "test.db")

    original = db_module.DATABASE_PATH
    db_module.DATABASE_PATH = db_path
    try:
        await db_module.init_db()
        yield db_path
    finally:
        db_module.DATABASE_PATH = original


@pytest.mark.asyncio
@pytest.mark.unit
async def test_all_four_template_types_are_seeded(fresh_db):
    """init_db() must seed templates for all four Quadlet types."""
    async with aiosqlite.connect(fresh_db) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT type FROM templates ORDER BY type") as cursor:
            rows = await cursor.fetchall()

    types = {row["type"] for row in rows}
    assert types == {"container", "volume", "network", "pod"}, (
        f"Expected all four template types, got: {types}"
    )


@pytest.mark.asyncio
@pytest.mark.unit
async def test_volume_template_has_volume_section(fresh_db):
    """Volume template content must start with [Volume]."""
    async with aiosqlite.connect(fresh_db) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT content FROM templates WHERE type = 'volume'"
        ) as cursor:
            row = await cursor.fetchone()

    assert row is not None, "Volume template not found"
    assert "[Volume]" in row["content"], f"Volume template missing [Volume] section: {row['content']!r}"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_network_template_has_network_section(fresh_db):
    """Network template content must start with [Network]."""
    async with aiosqlite.connect(fresh_db) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT content FROM templates WHERE type = 'network'"
        ) as cursor:
            row = await cursor.fetchone()

    assert row is not None, "Network template not found"
    assert "[Network]" in row["content"], f"Network template missing [Network] section: {row['content']!r}"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_pod_template_has_pod_section(fresh_db):
    """Pod template content must start with [Pod]."""
    async with aiosqlite.connect(fresh_db) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT content FROM templates WHERE type = 'pod'"
        ) as cursor:
            row = await cursor.fetchone()

    assert row is not None, "Pod template not found"
    assert "[Pod]" in row["content"], f"Pod template missing [Pod] section: {row['content']!r}"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_container_template_still_present(fresh_db):
    """Existing Container template must still be seeded."""
    async with aiosqlite.connect(fresh_db) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT content FROM templates WHERE type = 'container'"
        ) as cursor:
            row = await cursor.fetchone()

    assert row is not None, "Container template not found"
    assert "[Container]" in row["content"]


@pytest.mark.asyncio
@pytest.mark.unit
async def test_seeding_is_idempotent(fresh_db):
    """Running init_db() a second time must not duplicate templates."""
    import core.database as db_module
    original = db_module.DATABASE_PATH
    db_module.DATABASE_PATH = fresh_db
    try:
        await db_module.init_db()  # second run
    finally:
        db_module.DATABASE_PATH = original

    async with aiosqlite.connect(fresh_db) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT COUNT(*) AS count FROM templates") as cursor:
            row = await cursor.fetchone()

    assert row["count"] == 4, f"Expected exactly 4 templates after two init_db() calls, got {row['count']}"
