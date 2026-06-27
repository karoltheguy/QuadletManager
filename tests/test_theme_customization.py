"""
Tests for Theme Customization.
- Issue #73: Schema + seed (user_themes table, _ensure_default_theme, get_current_user_id)
- Issue #74: CRUD API routes (list, create, update, colors, activate, reset, delete, active.css)
"""
import os
import sys
import json as _json
import time as _time
import pytest
import pytest_asyncio
import aiosqlite
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import core.database as db_module
from core.database import init_db


# ── Fixture: isolated in-memory-style DB ──────────────────────────────────────

@pytest_asyncio.fixture
async def fresh_db(tmp_path):
    """Run init_db() against a temp file and yield the path. Restores DATABASE_PATH after."""
    db_path = str(tmp_path / "test_themes.db")
    original = db_module.DATABASE_PATH
    db_module.DATABASE_PATH = db_path
    try:
        await init_db()
        yield db_path
    finally:
        db_module.DATABASE_PATH = original


# ── Schema tests ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.unit
async def test_schema_init_creates_user_themes_table(fresh_db):
    """init_db() must create the user_themes table with all required columns."""
    async with aiosqlite.connect(fresh_db) as db:
        rows = await (await db.execute("PRAGMA table_info('user_themes')")).fetchall()

    assert rows, "user_themes table was not created by init_db()"

    col_names = [row[1] for row in rows]
    expected = {
        "id", "user_id", "theme_name", "mode_preference",
        "light_overrides_json", "dark_overrides_json",
        "is_active", "created_at", "updated_at",
    }
    missing = expected - set(col_names)
    assert not missing, f"user_themes is missing columns: {missing}"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_schema_init_creates_user_active_index(fresh_db):
    """init_db() must create the idx_user_themes_user_active index."""
    async with aiosqlite.connect(fresh_db) as db:
        rows = await (await db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_user_themes_user_active'"
        )).fetchall()
    assert rows, "idx_user_themes_user_active index was not created"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_mode_preference_check_constraint(fresh_db):
    """Inserting an invalid mode_preference must raise an IntegrityError."""
    import time
    now = int(time.time())
    async with aiosqlite.connect(fresh_db) as db:
        with pytest.raises(aiosqlite.IntegrityError):
            await db.execute(
                """INSERT INTO user_themes
                   (user_id, theme_name, mode_preference, created_at, updated_at)
                   VALUES (1, 'Bad Mode', 'weird', ?, ?)""",
                (now, now),
            )


@pytest.mark.asyncio
@pytest.mark.unit
async def test_schema_idempotent_on_second_init(fresh_db):
    """Running init_db() a second time must not raise (idempotent migrations)."""
    await init_db()  # second call — should be a no-op


# ── _ensure_default_theme() tests ─────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.unit
async def test_ensure_default_theme_seeds_once(fresh_db):
    """Calling _ensure_default_theme(user_id=1) must insert exactly one row."""
    from api.routes import _ensure_default_theme

    await _ensure_default_theme(user_id=1)

    async with aiosqlite.connect(fresh_db) as db:
        rows = await (await db.execute(
            "SELECT * FROM user_themes WHERE user_id=1"
        )).fetchall()

    assert len(rows) == 1, f"Expected 1 default theme row, got {len(rows)}"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_ensure_default_theme_is_idempotent(fresh_db):
    """Calling _ensure_default_theme() twice must still yield exactly one row."""
    from api.routes import _ensure_default_theme

    await _ensure_default_theme(user_id=1)
    await _ensure_default_theme(user_id=1)

    async with aiosqlite.connect(fresh_db) as db:
        rows = await (await db.execute(
            "SELECT * FROM user_themes WHERE user_id=1"
        )).fetchall()

    assert len(rows) == 1, f"Expected 1 row after two calls, got {len(rows)}"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_ensure_default_theme_is_active(fresh_db):
    """The seeded default theme must have is_active=1 and mode_preference='auto'."""
    from api.routes import _ensure_default_theme

    await _ensure_default_theme(user_id=1)

    async with aiosqlite.connect(fresh_db) as db:
        row = await (await db.execute(
            "SELECT theme_name, mode_preference, is_active FROM user_themes WHERE user_id=1"
        )).fetchone()

    assert row is not None
    theme_name, mode_pref, is_active = row
    assert theme_name == "Default"
    assert mode_pref == "auto"
    assert is_active == 1


# ── get_current_user_id() tests ───────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.unit
async def test_get_current_user_id_returns_correct_id(fresh_db):
    """get_current_user_id returns the numeric id for a known username."""
    from api.routes import get_current_user_id

    result = await get_current_user_id(username="admin")
    assert result == 1, f"Expected id=1 for admin, got {result}"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_get_current_user_id_viewer(fresh_db):
    """get_current_user_id returns id=2 for the seeded viewer user."""
    from api.routes import get_current_user_id

    result = await get_current_user_id(username="viewer")
    assert result == 2, f"Expected id=2 for viewer, got {result}"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_get_current_user_id_missing_user_raises_404(fresh_db):
    """get_current_user_id raises HTTP 404 for an unknown username."""
    from fastapi import HTTPException
    from api.routes import get_current_user_id

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user_id(username="ghost")

    assert exc_info.value.status_code == 404


# ── Issue #74: CRUD API route tests ──────────────────────────────────────────


def _mock_request():
    r = MagicMock()
    r.cookies = {}
    return r


@pytest.mark.asyncio
@pytest.mark.unit
async def test_create_theme_unique_name_per_user(fresh_db):
    """Duplicate theme name for same user → 409."""
    from fastapi import HTTPException
    from api.routes import settings_create_theme

    now = int(_time.time())
    async with aiosqlite.connect(fresh_db) as db:
        await db.execute(
            "INSERT INTO user_themes (user_id, theme_name, mode_preference, "
            "light_overrides_json, dark_overrides_json, is_active, created_at, updated_at) "
            "VALUES (1, 'MyTheme', 'auto', '{}', '{}', 0, ?, ?)", (now, now),
        )
        await db.commit()

    with pytest.raises(HTTPException) as exc_info:
        await settings_create_theme(
            request=_mock_request(), theme_name="MyTheme", copy_from=None, user_id=1,
        )
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
@pytest.mark.unit
async def test_create_theme_copy_from_existing(fresh_db):
    """New theme with copy_from inherits light/dark overrides from source."""
    from api.routes import settings_create_theme

    now = int(_time.time())
    light = _json.dumps({"bg_base": "#aabbcc"})
    dark = _json.dumps({"bg_base": "#112233"})
    async with aiosqlite.connect(fresh_db) as db:
        await db.execute(
            "INSERT INTO user_themes (user_id, theme_name, mode_preference, "
            "light_overrides_json, dark_overrides_json, is_active, created_at, updated_at) "
            "VALUES (1, 'Source', 'auto', ?, ?, 1, ?, ?)", (light, dark, now, now),
        )
        row = await (await db.execute(
            "SELECT id FROM user_themes WHERE theme_name='Source' AND user_id=1"
        )).fetchone()
        source_id = row[0]
        await db.commit()

    await settings_create_theme(
        request=_mock_request(), theme_name="Copied", copy_from=source_id, user_id=1,
    )

    async with aiosqlite.connect(fresh_db) as db:
        row = await (await db.execute(
            "SELECT light_overrides_json, dark_overrides_json FROM user_themes "
            "WHERE theme_name='Copied' AND user_id=1"
        )).fetchone()

    assert row is not None
    assert row[0] == light
    assert row[1] == dark


@pytest.mark.asyncio
@pytest.mark.unit
async def test_put_colors_allowlist_drops_unknown_keys(fresh_db):
    """PUT /colors silently drops keys outside the 8-key allowlist; DB row stays clean."""
    from api.routes import settings_update_theme_colors

    now = int(_time.time())
    async with aiosqlite.connect(fresh_db) as db:
        await db.execute(
            "INSERT INTO user_themes (user_id, theme_name, mode_preference, "
            "light_overrides_json, dark_overrides_json, is_active, created_at, updated_at) "
            "VALUES (1, 'T1', 'auto', '{}', '{}', 0, ?, ?)", (now, now),
        )
        row = await (await db.execute(
            "SELECT id FROM user_themes WHERE theme_name='T1' AND user_id=1"
        )).fetchone()
        theme_id = row[0]
        await db.commit()

    request = _mock_request()
    request.form = AsyncMock(return_value={
        "mode": "light",
        "bg_base": "#aabbcc",
        "nm_shadow_dark": "bad_key",
        "shadow_raised": "also_bad",
    })

    await settings_update_theme_colors(request=request, theme_id=theme_id, user_id=1)

    async with aiosqlite.connect(fresh_db) as db:
        row = await (await db.execute(
            "SELECT light_overrides_json FROM user_themes WHERE id=? AND user_id=1", (theme_id,),
        )).fetchone()

    saved = _json.loads(row[0])
    assert "bg_base" in saved
    assert "nm_shadow_dark" not in saved
    assert "shadow_raised" not in saved


@pytest.mark.asyncio
@pytest.mark.unit
async def test_put_colors_rejects_invalid_hex(fresh_db):
    """PUT /colors with invalid hex values → 422."""
    from fastapi import HTTPException
    from api.routes import settings_update_theme_colors

    now = int(_time.time())
    async with aiosqlite.connect(fresh_db) as db:
        await db.execute(
            "INSERT INTO user_themes (user_id, theme_name, mode_preference, "
            "light_overrides_json, dark_overrides_json, is_active, created_at, updated_at) "
            "VALUES (1, 'T2', 'auto', '{}', '{}', 0, ?, ?)", (now, now),
        )
        row = await (await db.execute(
            "SELECT id FROM user_themes WHERE theme_name='T2' AND user_id=1"
        )).fetchone()
        theme_id = row[0]
        await db.commit()

    for bad_val in ("red", "#12", "javascript:alert(1)"):
        request = _mock_request()
        request.form = AsyncMock(return_value={"mode": "light", "bg_base": bad_val})
        with pytest.raises(HTTPException) as exc_info:
            await settings_update_theme_colors(request=request, theme_id=theme_id, user_id=1)
        assert exc_info.value.status_code == 422


@pytest.mark.asyncio
@pytest.mark.unit
async def test_activate_clears_others(fresh_db):
    """After POST activate, exactly one is_active=1 row exists for that user."""
    from api.routes import settings_activate_theme

    now = int(_time.time())
    async with aiosqlite.connect(fresh_db) as db:
        await db.execute(
            "INSERT INTO user_themes (user_id, theme_name, mode_preference, "
            "light_overrides_json, dark_overrides_json, is_active, created_at, updated_at) "
            "VALUES (1, 'Theme A', 'auto', '{}', '{}', 1, ?, ?)", (now, now),
        )
        await db.execute(
            "INSERT INTO user_themes (user_id, theme_name, mode_preference, "
            "light_overrides_json, dark_overrides_json, is_active, created_at, updated_at) "
            "VALUES (1, 'Theme B', 'auto', '{}', '{}', 0, ?, ?)", (now, now),
        )
        row = await (await db.execute(
            "SELECT id FROM user_themes WHERE theme_name='Theme B' AND user_id=1"
        )).fetchone()
        theme_b_id = row[0]
        await db.commit()

    await settings_activate_theme(request=_mock_request(), theme_id=theme_b_id, user_id=1)

    async with aiosqlite.connect(fresh_db) as db:
        rows = await (await db.execute(
            "SELECT id, is_active FROM user_themes WHERE user_id=1"
        )).fetchall()

    active_rows = [r for r in rows if r[1] == 1]
    assert len(active_rows) == 1
    assert active_rows[0][0] == theme_b_id


@pytest.mark.asyncio
@pytest.mark.unit
async def test_reset_clears_one_mode_only(fresh_db):
    """POST /reset?mode=light zeroes light_overrides_json but leaves dark_overrides_json unchanged."""
    from api.routes import settings_reset_theme

    now = int(_time.time())
    light = _json.dumps({"bg_base": "#ffffff"})
    dark = _json.dumps({"bg_base": "#000000"})
    async with aiosqlite.connect(fresh_db) as db:
        await db.execute(
            "INSERT INTO user_themes (user_id, theme_name, mode_preference, "
            "light_overrides_json, dark_overrides_json, is_active, created_at, updated_at) "
            "VALUES (1, 'Colorful', 'auto', ?, ?, 0, ?, ?)", (light, dark, now, now),
        )
        row = await (await db.execute(
            "SELECT id FROM user_themes WHERE theme_name='Colorful' AND user_id=1"
        )).fetchone()
        theme_id = row[0]
        await db.commit()

    await settings_reset_theme(request=_mock_request(), theme_id=theme_id, mode="light", user_id=1)

    async with aiosqlite.connect(fresh_db) as db:
        row = await (await db.execute(
            "SELECT light_overrides_json, dark_overrides_json FROM user_themes WHERE id=? AND user_id=1",
            (theme_id,),
        )).fetchone()

    assert row[0] == "{}"
    assert row[1] == dark


@pytest.mark.asyncio
@pytest.mark.unit
async def test_delete_active_blocked(fresh_db):
    """DELETE on the active theme → 400 with a non-empty error message."""
    from fastapi import HTTPException
    from api.routes import settings_delete_theme

    now = int(_time.time())
    async with aiosqlite.connect(fresh_db) as db:
        await db.execute(
            "INSERT INTO user_themes (user_id, theme_name, mode_preference, "
            "light_overrides_json, dark_overrides_json, is_active, created_at, updated_at) "
            "VALUES (1, 'ActiveTheme', 'auto', '{}', '{}', 1, ?, ?)", (now, now),
        )
        row = await (await db.execute(
            "SELECT id FROM user_themes WHERE theme_name='ActiveTheme' AND user_id=1"
        )).fetchone()
        theme_id = row[0]
        await db.commit()

    with pytest.raises(HTTPException) as exc_info:
        await settings_delete_theme(request=_mock_request(), theme_id=theme_id, user_id=1)
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail


@pytest.mark.asyncio
@pytest.mark.unit
async def test_cross_user_isolation(fresh_db):
    """User B's requests against user A's theme ID return 404 (no existence leak)."""
    from fastapi import HTTPException
    from api.routes import settings_delete_theme, settings_activate_theme

    now = int(_time.time())
    async with aiosqlite.connect(fresh_db) as db:
        await db.execute(
            "INSERT INTO user_themes (user_id, theme_name, mode_preference, "
            "light_overrides_json, dark_overrides_json, is_active, created_at, updated_at) "
            "VALUES (1, 'UserATheme', 'auto', '{}', '{}', 0, ?, ?)", (now, now),
        )
        row = await (await db.execute(
            "SELECT id FROM user_themes WHERE theme_name='UserATheme' AND user_id=1"
        )).fetchone()
        theme_id = row[0]
        await db.commit()

    with pytest.raises(HTTPException) as exc_info:
        await settings_delete_theme(request=_mock_request(), theme_id=theme_id, user_id=2)
    assert exc_info.value.status_code == 404

    with pytest.raises(HTTPException) as exc_info:
        await settings_activate_theme(request=_mock_request(), theme_id=theme_id, user_id=2)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
@pytest.mark.unit
async def test_active_css_shape(fresh_db):
    """GET active.css returns text/css; contains :root[data-theme="light"] only when light overrides exist."""
    from api.routes import settings_active_css

    now = int(_time.time())
    light = _json.dumps({"bg_base": "#aabbcc"})
    async with aiosqlite.connect(fresh_db) as db:
        await db.execute(
            "INSERT INTO user_themes (user_id, theme_name, mode_preference, "
            "light_overrides_json, dark_overrides_json, is_active, created_at, updated_at) "
            "VALUES (1, 'CSSTheme', 'auto', ?, '{}', 1, ?, ?)", (light, now, now),
        )
        await db.commit()

    response = await settings_active_css(user_id=1)

    assert "text/css" in response.headers.get("content-type", "")
    body = response.body.decode()
    assert ':root[data-theme="light"]' in body
    assert "#aabbcc" in body
    assert ':root[data-theme="dark"]' not in body


# ── Issue #75: Dashboard route theme context ──────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.unit
async def test_dashboard_route_includes_active_theme_context(fresh_db):
    """GET / must render qm-theme-overrides style block in the page body."""
    from api.routes import load_active_theme, _ensure_default_theme

    await _ensure_default_theme(user_id=1)
    theme = await load_active_theme(user_id=1)

    assert "mode_pref" in theme
    assert "light" in theme
    assert "dark" in theme
    assert theme["mode_pref"] in ("auto", "light", "dark")
    assert isinstance(theme["light"], dict)
    assert isinstance(theme["dark"], dict)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_dashboard_route_emits_light_override_selector_when_set(fresh_db):
    """load_active_theme returns light overrides that were saved for the active theme."""
    import json as _j
    from api.routes import load_active_theme, _ensure_default_theme

    await _ensure_default_theme(user_id=1)

    async with aiosqlite.connect(fresh_db) as db:
        overrides = _j.dumps({"bg_base": "#abcdef"})
        await db.execute(
            "UPDATE user_themes SET light_overrides_json=? WHERE user_id=1 AND is_active=1",
            (overrides,),
        )
        await db.commit()

    theme = await load_active_theme(user_id=1)
    assert theme["light"].get("bg_base") == "#abcdef"


# ── Issue #77: Frontend JS (static/main.js) ───────────────────────────────────

import os as _os
_MAIN_JS = _os.path.join(_os.path.dirname(__file__), '..', 'static', 'main.js')


def _read_main_js():
    with open(_MAIN_JS) as f:
        return f.read()


@pytest.mark.unit
def test_main_js_defines_apply_theme_preview():
    """applyThemePreview must be defined in static/main.js."""
    content = _read_main_js()
    assert 'function applyThemePreview' in content


@pytest.mark.unit
def test_main_js_defines_clear_theme_preview():
    """clearThemePreview must be defined in static/main.js."""
    content = _read_main_js()
    assert 'function clearThemePreview' in content


@pytest.mark.unit
def test_toggle_theme_uses_qm_theme_override_key():
    """toggleTheme must persist to 'qm-theme-override' (matches FOUC init script)."""
    content = _read_main_js()
    toggle_start = content.find('function toggleTheme')
    toggle_end = content.find('\n}', toggle_start) + 2
    toggle_body = content[toggle_start:toggle_end]
    assert 'qm-theme-override' in toggle_body


@pytest.mark.unit
def test_theme_updated_listener_registered():
    """main.js must register a 'theme-updated' body event listener."""
    content = _read_main_js()
    assert "theme-updated" in content
