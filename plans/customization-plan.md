# Theme Customization Feature — Forgejo Issue #65

## Context

Issue #65 asks for a Themes section in Settings so users can: (1) pick Auto / Light / Dark day-night mode, (2) customize colors for both light and dark palettes via a curated editor, and (3) create, name, save, and switch between multiple custom themes. The issue is labeled `size: complex` and `prio: could-have`, and the body explicitly recommends breaking it down.

The user has confirmed full-scope implementation in one pass, with preferences persisted per-user in SQLite (not localStorage), and a curated color editor that exposes only the base palette — the neumorphic shadow variables (`--nm-shadow-*`, `--shadow-raised*`) stay locked so the visual language can't be broken by user color choices.

The codebase is unusually well-prepared: CSS variables are cleanly abstracted at `static/style.css:6-118`, theming uses the `[data-theme]` attribute pattern with an `@media (prefers-color-scheme)` fallback, there's already a `toggleTheme()` + FOUC-prevention script at `templates/dashboard.html:5-14` / `static/main.js:13-27`, and the settings page already has a sidenav pattern for adding new sections. The real engineering work is in the backend CRUD, the color editor UI, and — most importantly — getting the FOUC story right when custom colors are involved.

## Design decisions (confirmed with user)

1. **Scope:** all three phases in one pass (tri-state + color editor + named multi-theme management).
2. **Persistence:** per-user rows in SQLite, new `user_themes` table. HTMX-driven routes mirroring the existing `/api/settings/*` pattern at `api/routes.py:441-786`.
3. **Editor granularity:** curated ~8 base colors per mode. Shadow/radius variables are NOT user-editable — they're dropped server-side by an allowlist, guaranteeing the neumorphic look is preserved.
4. **FOUC strategy:** server-renders the active theme's color overrides as an inline `<style>` block in `dashboard.html` `<head>`, placed *after* the main stylesheet so same-specificity rules win. This is the only approach that avoids a flash of default colors on reload. No JS/fetch for the critical path.
5. **Quick-toggle preserved:** the navbar sun/moon button stays as a 2-state quick-flip for "I want dark right now" muscle memory. The tri-state (auto/light/dark) selector lives inside the themes editor. Both modes of a custom theme are pre-rendered into the inline `<style>`, so the quick-toggle remains instant with zero flash.

## Database schema

Add to `core/database.py` inside `init_db()` after the existing `settings` table block (after line 114), following the repo's `CREATE TABLE IF NOT EXISTS` pattern (see lines 21-25, 46-50 for the try/except ALTER migration style).

```sql
CREATE TABLE IF NOT EXISTS user_themes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    theme_name TEXT NOT NULL,
    mode_preference TEXT NOT NULL DEFAULT 'auto'
        CHECK(mode_preference IN ('auto', 'light', 'dark')),
    light_overrides_json TEXT NOT NULL DEFAULT '{}',
    dark_overrides_json  TEXT NOT NULL DEFAULT '{}',
    is_active INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
    UNIQUE(user_id, theme_name)
);
CREATE INDEX IF NOT EXISTS idx_user_themes_user_active
    ON user_themes(user_id, is_active);
```

**Notes:**
- Two JSON columns (one per mode) rather than one nested blob — maps 1:1 to the "edit light / edit dark" UI split and keeps updates trivial.
- `mode_preference` lives on the theme, not separately — a user's saved theme can carry its preferred mode (e.g. "my ocean theme only makes sense in dark").
- `is_active` uniqueness is enforced by the POST `/activate` handler (SQLite partial unique indexes are awkward): `UPDATE user_themes SET is_active=0 WHERE user_id=?` then set the new one in a transaction.
- No Alembic — this repo uses native `CREATE TABLE IF NOT EXISTS`. Existing users get a default theme lazily via `_ensure_default_theme(user_id)` helper invoked from the GET route.

## Backend routes

All under `/api/settings/themes`, added to `api/routes.py` alongside the existing settings block at lines 441-786. Each takes `username: str = Depends(get_current_username)` (see `routes.py:103`) and resolves to `user_id` via a new helper:

```python
async def get_current_user_id(username: str = Depends(get_current_username)) -> int:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        row = await (await db.execute("SELECT id FROM users WHERE username=?", (username,))).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return row[0]
```

Endpoint table:

| Method | Path | Purpose | Returns |
|---|---|---|---|
| GET    | `/api/settings/themes` | List user's themes + editor for active theme (seeds default on first call) | HTML partial |
| POST   | `/api/settings/themes` | Create new theme (form: `theme_name`, `copy_from`) | HTML partial |
| PUT    | `/api/settings/themes/{id}` | Rename / update `mode_preference` | HTML partial |
| PUT    | `/api/settings/themes/{id}/colors` | Save one mode's overrides (form: `mode=light\|dark`, 8 hex fields) | HTML partial + `HX-Trigger: theme-updated` |
| POST   | `/api/settings/themes/{id}/activate` | Set active, clear others | HTML partial + `HX-Trigger: theme-updated` |
| POST   | `/api/settings/themes/{id}/reset` | Clear one mode's overrides back to defaults | HTML partial |
| DELETE | `/api/settings/themes/{id}` | Delete theme (400 if active or default) | HTML partial |
| GET    | `/api/settings/themes/active.css` | CSS of the active theme's overrides as `:root[data-theme="..."]{...}` | `text/css` |

**Server-side allowlist** (the guardrail that keeps neumorphic intact). The 8 editable keys:
`bg_base, bg_surface, text_primary, text_muted, brand_primary, success, danger, border_color`.
Each value must match `^#[0-9a-fA-F]{6}$`. Keys outside the allowlist are silently dropped; invalid hex → 422. The PUT `/colors` handler builds a dict only from allowlisted + valid keys before serializing to JSON.

**Cross-user isolation:** every query uses `WHERE id=? AND user_id=?`. A user hitting another user's `theme_id` gets 404, never 403 (doesn't leak existence).

## Frontend partial — `templates/partials/settings_themes.html` (new file)

Three stacked sections inside a root wrapper `<div id="themes-root">` (so every HTMX response can swap-in the full partial):

1. **Saved themes list** — cards showing name, a strip of 6 color swatches, a `mode_preference` badge (Auto/Light/Dark), and Activate / Rename / Delete buttons. HTMX-driven: `hx-target="#themes-root"`, `hx-swap="outerHTML"`.

2. **Create theme form** — `hx-post="/api/settings/themes"` with `theme_name` input and a `copy_from` `<select>` populated from existing themes (plus a "Defaults" option).

3. **Color editor for the active theme**:
   - Header shows active theme name.
   - `mode_preference` radio group (Auto / Light / Dark) at top, `hx-put="/api/settings/themes/{id}"` on change.
   - Segmented control `[ Light mode | Dark mode ]` flips a local `data-editing-mode` attribute. Both sub-forms are Jinja-rendered, one hidden via CSS — no extra round-trip to switch.
   - Each sub-form: 8 paired inputs (one `<input type="color">` + one hex text input; JS keeps them in sync).
   - Buttons: **Preview** (apply unsaved, pure client-side), **Save** (`PUT .../colors`), **Reset mode** (`POST .../reset`), **Cancel preview**.

## FOUC-prevention — the load-bearing edit

`templates/dashboard.html:5-14` currently only reads `localStorage['qm-theme']`. It needs to:
1. Resolve tri-state `auto` → matchMedia → `data-theme`.
2. Honor a per-device quick-toggle override separately from the server-stored preference.

The **color overrides** can't come from JS — by the time JS runs CSS has already applied. Instead, the dashboard route (`api/routes.py:172-181`) loads the user's active theme and passes it into the template context:

```python
active_theme = await load_active_theme(user_id)  # {mode_pref, light: {...}, dark: {...}}
return templates.TemplateResponse(request, "dashboard.html", {
    ...,
    "active_theme_mode_pref": active_theme["mode_pref"],
    "active_theme_light": active_theme["light"],
    "active_theme_dark":  active_theme["dark"],
})
```

Then in `dashboard.html` `<head>`, **after** the `<link rel="stylesheet" href="/static/style.css">` line (line 20):

```html
<script>
  (function () {
    try {
      var pref = {{ active_theme_mode_pref | tojson }};
      var quickOverride = localStorage.getItem('qm-theme-override');
      var effective = quickOverride || pref || 'auto';
      var resolved = effective === 'auto'
        ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
        : effective;
      document.documentElement.setAttribute('data-theme', resolved);
    } catch (e) {}
  })();
</script>
<style id="qm-theme-overrides">
  :root[data-theme="light"] {
    {% for k, v in active_theme_light.items() %}--{{ k|replace('_','-') }}: {{ v }};{% endfor %}
  }
  :root[data-theme="dark"] {
    {% for k, v in active_theme_dark.items() %}--{{ k|replace('_','-') }}: {{ v }};{% endfor %}
  }
</style>
```

Both modes emitted simultaneously → navbar quick-toggle flips `data-theme` instantly with zero flash and no re-fetch.

## Sidenav tab & content group — `templates/dashboard.html`

- **Around line 120** (after the closing `{% endif %}` of the Users tab — Themes is available to all users, no admin gate): add a new `.settings-sidenav-item` button `data-section="themes"` with an inline palette SVG icon.
- **Around line 255** (before `</div><!-- /.settings-main -->`): add
  ```html
  <div class="settings-group" data-group="themes" style="display:none">
    <div class="settings-section full-width">
      <h3 class="section-title mb-4">Theme Customization</h3>
      <div id="themes-root" hx-get="/api/settings/themes" hx-trigger="load">
        <p class="text-muted">Loading themes...</p>
      </div>
    </div>
  </div>
  ```
- No change to `showSettingsSection()` (`static/main.js:901-908`) — it's data-driven.

## `static/main.js` updates

1. **Rework `toggleTheme()` (lines 13-27)**: keep it as 2-state (light↔dark) for the navbar; change its localStorage key to `qm-theme-override` to match the new FOUC script; don't touch custom color overrides, just flip `data-theme`. The `qm-theme-overrides` `<style>` block already contains both modes, so the flip is instant.
2. **New `applyThemePreview(lightMap, darkMap)`**: writes/replaces a second `<style id="qm-theme-preview">` after `qm-theme-overrides` (higher source order wins). Used by the editor's Preview button.
3. **New `clearThemePreview()`**: removes the preview `<style>` element. Called on Cancel, on Save success, and on navigating away from the themes tab.
4. **Hex ↔ color-picker sync**: small event-delegation helper wired inside the themes partial (~20 LoC).
5. **Chart re-theming**: existing `applyChartTheme()` is already called from `toggleTheme()`. Also call it on `htmx:trigger` for `theme-updated` events so saved color changes re-color any charts.

## Critical files to modify

- `core/database.py` — add `user_themes` table + index
- `api/routes.py` — add 8 theme routes, `get_current_user_id` helper, dashboard route context
- `templates/dashboard.html` — FOUC script update, `<style id="qm-theme-overrides">` block, Themes sidenav tab, themes settings-group
- `templates/partials/settings_themes.html` — **new file**, full editor UI
- `static/main.js` — rework `toggleTheme()`, add preview helpers, chart re-theming listener
- `static/style.css` — minor: styles for theme card / swatch strip / segmented mode toggle (add to end of file, ~50 LoC)
- `tests/test_theme_customization.py` — **new file**, see below

## Reused patterns / functions

- `api/routes.py:103` `get_current_username` — base auth dependency the new `get_current_user_id` wraps.
- `api/routes.py:441-786` — HTMX-driven settings routes pattern (GET returns partial, mutating routes return refreshed partial).
- `core/database.py:21-25, 46-50` — `CREATE TABLE IF NOT EXISTS` + try/except `ALTER TABLE` migration pattern.
- `static/main.js:901-908` `showSettingsSection` — data-attribute tab switching.
- `static/style.css:6-118` — `:root[data-theme="..."]` variable architecture that the custom overrides hook into by selector match.
- `templates/partials/toast.html` + `HX-Trigger` — error / success notifications.
- `templates/partials/settings_servers.html`, `settings_users.html` — structural reference for the new `settings_themes.html`.

## Tests — `tests/test_theme_customization.py` (new file)

Follows existing pytest+asyncio pattern (`tests/test_rbac.py`) with Playwright for UI (`tests/test_settings_layout.py`, gated by `HAS_PLAYWRIGHT`).

**Backend unit (no server):**
1. `test_schema_init_creates_user_themes_table` — `PRAGMA table_info`, assert columns and check constraint.
2. `test_first_get_seeds_default_theme` — GET on fresh user → row exists, `is_active=1`, `mode_preference='auto'`.
3. `test_create_theme_unique_name_per_user` — duplicate name → 409.
4. `test_put_colors_allowlist_drops_unknown` — passing `nm_shadow_dark` in form is silently ignored; DB stays clean.
5. `test_put_colors_rejects_invalid_hex` — `red`, `#12`, `javascript:` → 422.
6. `test_activate_clears_others` — only one `is_active=1` per user after activate.
7. `test_delete_active_blocked` — 400.
8. `test_cross_user_isolation` — user B GET/PUT/DELETE on user A's theme → 404.
9. `test_active_css_returns_text_css_only_when_overrides_present` — empty overrides → empty body; populated → `:root[data-theme="..."] { --bg-base: #...; }`.
10. `test_mode_preference_check_constraint` — invalid value rejected.

**E2E (Playwright, `HAS_PLAYWRIGHT` gate, backend running):**
11. `test_themes_tab_appears_in_settings_sidenav`
12. `test_color_picker_change_applies_css_var` — change `--bg-base`, assert `getComputedStyle(body).backgroundColor` updated.
13. `test_neumorphic_shadows_preserved_after_custom_theme` — assert `getComputedStyle('.settings-section').boxShadow` still contains the 2-shadow composite.
14. `test_no_fouc_on_reload_with_active_custom_theme` — reload, snapshot `document.documentElement.getAttribute('data-theme')` at `DOMContentLoaded` via `page.add_init_script`; assert it's set before any paint.
15. `test_tri_state_auto_follows_os_preference` — `page.emulate_media(color_scheme='light')`, set `mode_preference=auto`, assert `data-theme="light"`.

Test 14 is the **acceptance gate** — if FOUC isn't fixed, the feature isn't shipped.

## Risks & gotchas

1. **FOUC is the #1 risk.** Any approach that applies colors *after* first paint (JS fetch, HTMX request, computed styles) will flash. The inline Jinja-rendered `<style>` is the only correct answer. Do not be tempted to lazy-load.
2. **Contrast / a11y** — a user can pick unreadable combos. Mitigation: show a WCAG 2.1 contrast ratio badge next to each text/background pair with a warning under 4.5:1, but don't hard-block.
3. **Neumorphic shadows can drift** if background color is radically far from the default. Mitigation: shadow vars stay locked, and the UI can carry a short note: "Shadow effects auto-compute from your base colors."
4. **Dev-auto-login / anonymous sessions** — check `api/routes.py:57-58` region: the session helper may return `admin` as a fallback. The new `get_current_user_id` resolves to seeded user `id=1` in that case, which is correct.
5. **HTMX swap shape** — every theme route must return the full `#themes-root` partial. Errors go via `HX-Trigger: toast` using the existing `partials/toast.html`, not by inlining fragments.
6. **Preview leaks** — if a user previews then navigates away, colors stick. Fix: hook `clearThemePreview()` into `showSettingsSection` when switching away from `themes`, and into HTMX `htmx:afterSwap` for the themes partial (the Save path re-renders anyway).
7. **SQLite FK cascade** requires `PRAGMA foreign_keys=ON`, which is off by default. Check current connection init; if not enabled, the user-delete path should clean up `user_themes` rows manually.
8. **Don't introduce a third `data-theme` value** (e.g. `data-theme="custom"`). The custom overrides selector must match `light`/`dark` so the quick-toggle stays coherent.

## TDD step ordering

**Phase 1 — Schema + seed**
1. Write test 1 (schema columns). Add `CREATE TABLE user_themes` to `core/database.py`. Green.
2. Write test 2 (lazy default seeding). Add `_ensure_default_theme` + `get_current_user_id` helper in `api/routes.py`. Add GET route scaffold. Green.

**Phase 2 — CRUD backend**
3. Tests 3, 5, 10. Implement POST create + validation.
4. Test 4 (allowlist). Implement PUT `/colors` with allowlist filter.
5. Test 6. Implement POST `/activate` (transaction).
6. Test 7. Implement DELETE with guard.
7. Test 8. Add `WHERE user_id=?` everywhere; cross-user test turns green.
8. Test 9. Implement GET `active.css`.

**Phase 3 — Template wiring (non-test render work)**
9. Create `templates/partials/settings_themes.html`.
10. Add sidenav tab + settings-group to `dashboard.html`.
11. Load active theme in dashboard route context; emit inline `<style id="qm-theme-overrides">` block after `style.css`; update FOUC script to use new `qm-theme-override` key.

**Phase 4 — Frontend JS**
12. Rework `toggleTheme()` (2-state, new key).
13. Add `applyThemePreview` / `clearThemePreview`.
14. Wire hex↔picker sync and HTMX `theme-updated` chart re-theme listener.

**Phase 5 — E2E (backend running)**
15. Tests 11-15. Test 14 (no FOUC) is the acceptance gate.

## Verification

After implementation:
- `pytest tests/test_theme_customization.py -v` — all unit tests green.
- Start the app (`uvicorn …`), log in, visit Settings → Themes. Manually:
  1. Default theme exists, is active, `mode_preference=auto`.
  2. Create a new theme "ocean"; copy from defaults.
  3. Edit dark mode colors (change `bg_base` to `#0a1628`, `brand_primary` to `#4fd1c5`). Save.
  4. Activate "ocean". Reload the page — verify **no flash of default colors** (this is test 14 manually).
  5. Click the navbar quick-toggle — verify instant flip to light with the light palette showing your edits, no flash.
  6. Open DevTools, confirm `.settings-section` still has the neumorphic 2-shadow `box-shadow`.
  7. Toggle OS color scheme (or `prefers-color-scheme` DevTools emulation). With `mode_preference=auto`, page follows.
  8. Delete "ocean" — blocked with a clear error because it's active. Activate default, retry delete — succeeds.
- `pytest tests/test_theme_customization.py -v -k "playwright"` (with `HAS_PLAYWRIGHT=1`) — all E2E tests green.
