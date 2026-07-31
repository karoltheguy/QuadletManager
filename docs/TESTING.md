# Testing Guide

## Overview

QuadletManager has three categories of tests:

| Category | Location | Requires | Run time |
|---|---|---|---|
| **Unit / async** | `tests/*.py` | Nothing (fully mocked) | ~2s |
| **Browser (E2E)** | `tests/e2e/*.py` | Running backend + Chromium | ~60s+ |
| **Podman** | `tests/podman/*.py` + `tests/e2e/test_podman_e2e.py` | A live Podman 5 host over SSH | ~45s |

The categories are intentionally separated into different directories so they can be run independently.

The `podman` suite is the only one that drives real podman, real systemd and the
real quadlet generator. Everything else mocks `pool.execute_command()`, so the
code paths that matter most in the field, the rootless scope in particular,
were never executed before it existed. See [Podman tests](#podman-tests).

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

## Podman tests

These run against a real, version-pinned Podman 5 host over SSH: real systemd,
real `podman`, and the real quadlet generator. They are marked `podman` and are
excluded from every other suite's marker expression.

This section covers using the fixture *here*. For what it is, a diagram of the
three targets, and how to lift it into another project, see
[The Podman test host](PODMAN_TEST_HOST.md). For what this work left undone,
including two app defects it uncovered, see
[Testing follow-ups](TESTING_TODO.md).

### The two targets

One suite, two interchangeable hosts, chosen entirely by environment variables
that are read in one place (`tests/podman/conftest.py`) and mirrored by
`scripts/seed_test_db.py`. The test bodies never mention either.

| Variable | Default | Meaning |
|---|---|---|
| `QM_PODMAN_HOST` | `localhost:2223` | `host:port`, used as `servers.ip_address` |
| `QM_PODMAN_USER` | `editor` | `servers.ssh_user` |
| `QM_PODMAN_KEY` | `tests/fixtures/test_key` | key to encrypt into `ssh_keys` |
| `QM_PODMAN_FORCE` | unset | remove leftovers from a crashed run instead of reporting them |
| `QM_APP_URL` | `http://localhost:8000` | where the browser journey finds the app |

**Target A, the container.** The default, and what CI runs.

```bash
sudo ./scripts/podman-e2e.sh up      # build and boot the host
./scripts/podman-e2e.sh status       # is it reachable?
./scripts/podman-e2e.sh test         # pytest -m podman
sudo ./scripts/podman-e2e.sh down
```

`up` and `down` are the only subcommands needing root. `status`, `test`, `shell`
and `logs` go over SSH and never prompt.

**Your own `podman ps` will not show this container.** It runs under *rootful*
podman, and rootful and rootless keep entirely separate container stores, so the
host looks like it never started. Use `sudo podman ps`, or
`./scripts/podman-e2e.sh status`, which checks the thing that actually matters
to the tests, namely SSH reachability, and needs no password.

This script deliberately does **not** use compose. A podman-only machine has no
compose provider at all, so every `docker compose -f docker-compose.test.yml`
command in these docs is unrunnable there. The compose profile exists for CI,
where the app container must reach the host by service name.

**Target B, loopback.** An opt-in fast path against your own machine's podman,
with no nesting and no image build.

```bash
sudo ./scripts/podman-e2e.sh setup-local     # once, ever
QM_PODMAN_HOST=localhost:22 QM_PODMAN_USER=quadlet-test \
  PYTHONPATH=. python -m pytest tests/ -m podman
sudo ./scripts/podman-e2e.sh teardown-local
```

`setup-local` creates a throwaway `quadlet-test` user rather than using your
account, and grants it the narrow sudoers allowlist documented in `README.MD`
rather than `NOPASSWD:ALL`. That makes this target the only check that the
documented sudoers policy is actually sufficient to run the app.

Both targets must produce the same result on the same commit. If they diverge,
the container is the source of truth, because it is what CI runs.

### Never run this suite in parallel

Whatever else you pass, do not pass `-n`. Every other suite here runs `-n auto`
and should; this one must not. There is exactly one host, and every test writes
`e2e-` fixtures under fixed names into the same two quadlet directories on it,
so two workers are two writers to one set of files. What you get is not a clean
failure in one test: `--dist=loadfile -n 2` produced 16 errors from a single
collision, with one worker's pre-flight tripping over the `e2e-test.pod` the
other had just installed.

`tests/podman/conftest.py` refuses to start under more than one worker, so this
costs a run rather than a debugging session. The check lives in a fixture rather
than in `pytest_configure`, deliberately: a conftest is imported whenever its
directory is *collected*, even when `-m` then deselects everything in it, so
raising at configure time took down `unit`, `unmarked`, `integration` and `e2e`
too.

`./scripts/podman-e2e.sh test` already gets this right. Use `-n0` if something
in your environment adds `-n auto` for you.

### Running the browser journeys

`tests/e2e/test_podman_e2e.py` needs an app instance whose database has been
seeded with the podman host. If you already have a dev server on port 8000, run
a second instance against a scratch database rather than seeding your real one:

```bash
export QUADLET_DB_PATH=/tmp/qm-podman/app.db
export QUADLET_MASTER_KEY=$(python -c "print('0'*64)")

mkdir -p /tmp/qm-podman
python -c "import asyncio, core.database as d; asyncio.run(d.init_db())"
QM_SEED_PODMAN=1 QM_PODMAN_HOST=localhost:2223 python scripts/seed_test_db.py

DEV_AUTO_LOGIN=1 PYTHONPATH=. uvicorn main:app --port 8001 &

QM_APP_URL=http://localhost:8001 python -m pytest tests/ -m podman
```

`QUADLET_MASTER_KEY` must match between the seeder and the app, or the encrypted
SSH key cannot be decrypted and the host is unreachable from the UI while
remaining perfectly reachable from the service-level tests.

Re-run the seeder after any `podman-e2e.sh up`, since a rebuilt host presents a
new SSH host key. See the host-key trap below.

### Safety rails

The loopback target writes global-scope units to your real
`/etc/containers/systemd`. So:

* Every file this suite creates is named `e2e-*`, and the teardown helper
  **raises** rather than deletes anything whose basename lacks that prefix.
* A pre-flight reports leftovers from a crashed run instead of deleting them.
  Inspect them, then re-run with `QM_PODMAN_FORCE=1`.
* Teardown runs in a `finally`, and additionally sweeps stray `e2e-` prefixed
  pods and containers.

### Two non-obvious host requirements

**Linger.** Without `/var/lib/systemd/linger/<user>`, `/run/user/<uid>` does not
exist for a non-interactive SSH session, so every command built with
`ROOTLESS_ENV_PREFIX` returns *empty output rather than an error*, and the
rootless half of the suite fails in ways that point nowhere near linger.
`tests/podman/test_podman_host_env.py` exists to catch this first.

**fuse-overlayfs.** Nested containers cannot use native overlay on an overlay
filesystem, so both the root and the user store need
`mount_program = "/usr/bin/fuse-overlayfs"` and the host needs `/dev/fuse`. The
symptom is a storage-driver error on the first `podman run`.

Related, and specific to Fedora's *container* base image: it ships
`newuidmap`/`newgidmap` **without** the file capabilities the host RPM sets.
`Dockerfile.podman-host` applies them with `setcap` and asserts the result,
because otherwise rootless podman inside fails with "should have setuid or have
filecaps setuid", which reads like a linger problem and is not one.

### Traps worth knowing before writing a podman test

**A `podman run` over SSH can hang forever on an inherited fd.** netavark starts
a background DNS daemon for the default bridge; it inherits the SSH channel's
stdout, so the client waits for an EOF that never comes even though the
container ran and exited. `pool.execute_command()` reads until EOF and hangs
identically. The normal path is safe, because quadlet containers are started by
`systemctl`, which owns the daemon's fds. But if a test shells out to
`podman run` directly, redirect first and read the file back:

```python
await pool.execute_command(sid, "podman run --rm img cmd > /tmp/out 2>&1")
output = await pool.execute_command(sid, "cat /tmp/out")
```

**Stopping a container cleanly needs both an init and a TERM trap.** With no
init, the payload is PID 1, the kernel applies no default signal action to
PID 1, SIGTERM is ignored and podman SIGKILLs after 10s (exit 137). With an
init but no trap, the process still dies *by* SIGTERM (exit 143). systemd
counts both as failure, so `systemctl stop` leaves the unit `failed` and a
lifecycle test cannot tell a clean stop from a crash. See
`tests/fixtures/quadlets/e2e-sleep.container`.

**Podman does not name every quadlet's unit `<base>.service`.** Only containers.
`e2e-test.pod` generates `e2e-test-pod.service`, and likewise `-volume` and
`-network`. `services/quadlet_naming.unit_name_for` maps everything to
`<base>.service`, so do not use it for non-container types.

**The `quadlets` table has no production writer.** `_unit_names_for_scope` reads
it, and `sync_engine.check_quadlets()` only polls rows that already exist. A
stats test must insert rows itself, or `unit_states` comes back empty and every
assertion passes vacuously.

**Rebuilding the host invalidates the app's pinned SSH host key.** Host keys are
TOFU-pinned into `servers.host_key` on first connect, and a rebuilt container
presents a brand new one, so the app fails with `HostKeyMismatchError`. The
symptom is misleading: the host is reachable over `ssh` from your terminal and
the service-level tests all pass, while only the *app* cannot talk to it, so the
browser journeys time out for no visible reason. Re-run the seeder, which clears
the stale pin:

```bash
QM_SEED_PODMAN=1 QM_PODMAN_HOST=localhost:2223 python scripts/seed_test_db.py
```

In CI this cannot happen, because `compose down -v` discards the volume with
the database in it.

**The committed test key is mode 644.** Git records only the executable bit, so
every clone gets a world-readable private key, which `ssh` refuses before
falling back to a password prompt. Anything shelling out to `ssh` must copy it
to a mode-600 file first and pass `BatchMode=yes`. `paramiko` does not care, so
`tests/podman/` itself is unaffected.

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