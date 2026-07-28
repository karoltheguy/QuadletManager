# Testing Guide

## Overview

QuadletManager has two categories of tests:

| Category | Location | Requires | Run time |
|---|---|---|---|
| **Unit / async** | `tests/*.py` | Nothing (fully mocked) | ~2s |
| **Browser (E2E)** | `tests/e2e/*.py` | Running backend + Chromium | ~60s+ |

The two categories are intentionally separated into different directories so they can be run independently.

---

## Installation

```bash
pip install -r requirements-test.txt
```

For E2E tests, also install the Playwright browser binaries (one-time):

```bash
playwright install chromium
```

---

## Running Tests

All tests require `PYTHONPATH=.` so that project packages (`core/`, `api/`, `services/`) are importable from the project root.

### Unit and async tests only (recommended for development)

```bash
PYTHONPATH=. pytest tests/ --ignore=tests/e2e/
```

These tests run entirely in-process with mocked dependencies. No backend, database, or browser is needed.

### Full suite (unit + browser)

```bash
PYTHONPATH=. pytest tests/
```

E2E tests require:
- The backend running on `http://localhost:8000` (`python main.py`)
- Chromium installed via `playwright install chromium`

E2E tests that cannot reach the backend will skip automatically rather than fail.

### Browser (E2E) tests only

```bash
PYTHONPATH=. pytest tests/e2e/
```

### Single file

```bash
PYTHONPATH=. pytest tests/test_container_events.py
```

### With coverage

```bash
PYTHONPATH=. pytest tests/ --ignore=tests/e2e/ --cov=. --cov-report=term-missing
```

---

## Test Structure

```
tests/
├── conftest.py (none — no shared fixtures needed at this level)
│
├── test_admin_panel_ui.py       # Route + template rendering
├── test_container_events.py     # Event logging and retrieval
├── test_crypto.py               # Encryption / master key lifecycle
├── test_file_deletion.py        # Quadlet file delete API
├── test_health_history.py       # Container health history recording
├── test_new_quadlet_modal.py    # Modal rendering
├── test_overview.py             # /api/overview endpoint (unit tests)
├── test_rbac.py                 # Role-based access control
├── test_scope_filter.py         # Scope filter logic
├── test_server_key_dropdown.py  # SSH key dropdown API (unit tests)
├── test_sockets.py              # WebSocket log streaming and terminal
├── test_ssh_key_api.py          # SSH key CRUD
├── test_stats_engine.py         # Stats normalisation and recording
├── test_stats_monitoring_dedup.py
├── test_sync_engine.py          # File-change poller logic
├── test_template_seeding.py     # Template DB seeding
├── test_theme_customization.py  # Theme schema and defaults
│
└── e2e/                         # Playwright browser tests
    ├── conftest.py              # Package-scoped Playwright fixtures (see below)
    ├── test_browser_notifications.py
    ├── test_e2e.py              # General UI smoke tests
    ├── test_expandable_inspector.py
    ├── test_inspector_stats_card.py
    ├── test_monitoring_ui.py
    ├── test_overview_e2e.py     # Overview tab (browser tests)
    ├── test_resizable_panels.py
    ├── test_server_key_dropdown_e2e.py
    ├── test_settings_layout.py
    ├── test_stats_e2e.py
    └── test_status_dots.py
```

---

## Configuration

### `pytest.ini`

```ini
[pytest]
asyncio_mode = auto
asyncio_default_fixture_loop_scope = function
```

`asyncio_mode = auto` means all `async def` test functions and fixtures are handled by pytest-asyncio automatically — no `@pytest.mark.asyncio` decorator is required (existing ones are harmless).

### `tests/e2e/conftest.py` — why it exists

pytest-playwright's `playwright`, `browser`, and related fixtures are `session`-scoped by default. Playwright's sync API calls `asyncio._set_running_loop(loop)` internally on every call and does not reset it when a test ends. This leaves the asyncio running-loop marker set, causing pytest-asyncio to raise `RuntimeError: Runner.run() cannot be called from a running event loop` when it tries to set up async tests that run after any Playwright test.

The fix (recommended in [playwright-pytest#289](https://github.com/microsoft/playwright-pytest/issues/289)) is to re-declare the Playwright fixture chain at `package` scope inside `tests/e2e/`. With `scope="package"`, pytest tears down Playwright's event loop after all browser tests finish, before any async unit tests run. The teardown calls `pw.stop()` which internally calls `loop.run_until_complete(...)`, which properly resets the asyncio running-loop state to `None`.

The fixtures re-declared at `package` scope are:
- `_pw_artifacts_folder`
- `playwright`
- `browser_context_args`
- `browser_type`
- `launch_browser`
- `browser`

---

## Writing Tests

### Async unit test

```python
import pytest
from unittest.mock import AsyncMock, patch

@patch("services.my_service.get_db_connection")
async def test_something(mock_db):
    mock_db.return_value.__aenter__ = AsyncMock(return_value=...)
    ...
```

No `@pytest.mark.asyncio` needed — `asyncio_mode = auto` handles it.

### Async fixture with database

```python
import pytest
from core.database import init_db, get_db_connection

@pytest.fixture
async def test_db(monkeypatch, tmp_path):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setenv("QUADLET_DB_PATH", db_path)
    await init_db()
    yield db_path
```

Use `await` directly — never `asyncio.run()` inside a fixture or test. `asyncio.run()` creates a new event loop and will raise `RuntimeError` if called from within an already-running loop (which pytest-asyncio sets up for every async test).

### Adding a new E2E test

Create a file in `tests/e2e/`. Use the `page: Page` fixture from pytest-playwright. Always guard with a `try/except` and `pytest.skip()` so the test skips gracefully when the backend is not running:

```python
from playwright.sync_api import Page, expect

def test_my_feature(page: Page):
    try:
        page.goto("http://localhost:8000/")
    except Exception:
        pytest.skip("Backend not running on localhost:8000")

    expect(page.locator("#my-element")).to_be_visible()
```

### Selecting elements in E2E tests

Two hazards have each cost more than one debugging cycle. Both are worth knowing before writing a locator.

**Prefer role-based locators over styling classes.** `#settings-pane .btn-primary` matches many buttons, and the first in DOM order is a permanently hidden one: the per-row "Save" button inside a server edit row (`<tr id="server-edit-row-N" style="display:none">` in `#servers-list`, rendered by `templates/partials/settings_servers.html`), which precedes the visible "Add Server" button. A locator using `.first` therefore resolves to an element that never becomes visible and times out on `to_be_visible()`. Hidden htmx edit rows are normal markup — the selector is what's wrong.

Use `get_by_role()` instead. Playwright matches roles against the accessibility tree, and `display:none` elements are not in it, so hidden rows are excluded automatically. This needs no `data-testid` hooks, and it exercises the same accessible name a screen reader would announce:

```python
# Times out: .first resolves to the hidden server-edit-row "Save" button
button = page.locator("#settings-pane .btn-primary").first

# Resolves to the one visible button; hidden rows are not in the a11y tree
button = page.locator("#settings-pane").get_by_role("button", name="Add Server")
```

Where several *visible* buttons share an accessible name — the light and dark color editors each have a "Save" — scope to the enclosing semantic container first, then match the role. Prefer a semantic attribute like `data-mode` over a styling class:

```python
dark_form = page.locator("form.color-editor-form[data-mode='dark']")
button = dark_form.get_by_role("button", name="Save")
```

**Guard what you measure.** A test that reads a computed style can pass vacuously: if the locator resolved to the wrong element, or the page is in the wrong theme, the assertion measures some unrelated default and reports green without ever exercising the code under test. Before asserting on a measured value, pin the state you intended to test so a wrong-state run fails loudly:

```python
# Pin the measured background to the color actually under test, so a
# wrong-element or wrong-theme measurement fails here rather than
# silently reporting a passing contrast ratio below.
expected_bg_hex = _normalize_color(_HOSTILE_BRAND)
assert button_bg_hex == expected_bg_hex, (
    f"Expected the measured button background-color to be the hostile "
    f"saved brand_primary {expected_bg_hex!r}, but measured "
    f"{button_bg_hex!r} instead — the button/theme state is wrong, so "
    f"the contrast ratio below would not be testing the fix."
)
```

Worked example of both patterns: `tests/e2e/test_theme_on_primary_contrast_e2e.py`.

### Asserting computed styles: suppress transitions first

`getComputedStyle` returns the value of the *current animation frame*, not the
settled value. `static/style.css` transitions some properties and not others —
`.btn`, for example, transitions `color` (0.18s) but not `background-color` — so
a test that flips `data-theme` and reads immediately sees the new background
paired with the **old** foreground, and any contrast assertion on that pair is
measuring a frame that never appears at rest.

The symptom is misleading: forcing `color: red !important` computes as something
like `rgb(255, 234, 234)`, which looks like the browser blending author styles
rather than an interpolated frame. Issue #225 lost a full debugging cycle to
this and produced a wrong root cause (native `<button>` dark-mode styling) before
the transition was identified.

Suppress transitions right after navigation, so assertions measure the settled
state:

```python
page.add_style_tag(content="""
    *, *::before, *::after {
        transition: none !important;
        animation: none !important;
    }
""")
```

Prefer this over `page.wait_for_timeout(...)`: a sleep re-introduces the flake
the moment someone lengthens a transition duration, and it slows every run.

### Selector ambiguity in settings

Several settings partials render a hidden inline-edit `<form>` per table row
*before* the always-visible "add" form. A bare
`#settings-pane button.btn-primary` therefore resolves `.first` to a
`display: none` element, and the test fails on visibility rather than on what it
meant to assert. Scope to the visible form — for example
`#settings-pane .add-server-form button.btn-primary`.