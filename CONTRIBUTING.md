# Contributing to QuadletManager

Thanks for taking an interest. This project manages real servers over SSH, so
the bar for correctness is higher than the line count suggests. The
contribution process itself is deliberately light.

Small fixes need no ceremony: open a pull request and we'll go from there. For
anything larger, open an issue first so we don't both build the same thing.

---

## Getting set up

**You need:** Python 3.12+, Node.js 20+, and a container engine (Docker or
Podman with `docker compose` available) for the integration and browser tests.

```bash
git clone https://github.com/karoltheguy/QuadletManager.git
cd QuadletManager

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-test.txt

npm ci
```

`npm ci` is not optional, even though this is mostly a Python project. Its
`postinstall` hook runs `npm run copy-assets`, which copies Monaco, xterm and
quadlet-lint out of `node_modules/` into `static/vendor/`. That directory is
`.gitignore`d, so a fresh clone has no frontend vendor assets until you run it,
and the editor and terminal panes will simply fail to load.

### Running the app

```bash
export QUADLET_MASTER_KEY=$(openssl rand -hex 32)
uvicorn main:app --host 0.0.0.0 --port 8000
```

The master key encrypts stored SSH private keys. If you leave it unset, a dev
key is generated and persisted to `master.key` next to `quadlets.db`. That is
fine locally, never in production. First startup seeds `admin`/`admin` and
`viewer`/`viewer`.

Setting `DEV_AUTO_LOGIN=1` skips the login screen, which is handy when
iterating on UI.

See [docs/SETUP.MD](docs/SETUP.MD) if you want to point it at a real server.

---

## Running the tests

CI splits the suite into four jobs by pytest marker. Running the same split
locally is the most reliable way to know your PR will go green:

| Suite | Command | Needs |
|---|---|---|
| `unit` | `python -m pytest tests/ -m unit -n auto` | nothing |
| `unmarked` | `python -m pytest tests/ -m "not unit and not integration and not e2e" -n auto` | nothing |
| `integration` | `python -m pytest tests/ -m integration -n auto --dist=loadfile` | mock environment |
| `e2e` | `python -m pytest tests/ -m e2e -n auto --dist=loadfile` | mock environment + Chromium |

The first two run fully mocked in a couple of seconds and cover most changes.

For `integration` and `e2e`, start the mock environment first. It boots a
container running real systemd to stand in for a remote host:

```bash
docker compose -f docker-compose.test.yml up -d --build
playwright install chromium          # one-time, for e2e only
# ... run tests ...
docker compose -f docker-compose.test.yml down -v
```

**Use `python -m pytest`, not bare `pytest`.** The `python -m` form puts the
current directory on `sys.path`, which is what makes the top-level `core/`,
`api/` and `services/` packages importable. Bare `pytest` does not, and every
import fails; `PYTHONPATH=. pytest` is the equivalent if you prefer it.

A per-test timeout of 120s is enforced by `pytest.ini`. If a test trips it,
that's a real hang, not a slow machine.

[docs/TESTING.md](docs/TESTING.md) covers test layout, fixtures, and two
locator hazards in the Playwright tests that have each cost real debugging
time. Read that section before writing an E2E test.

### Marking new tests

Anything that needs Docker gets `@pytest.mark.integration`; anything driving a
browser gets `@pytest.mark.e2e`; fast mocked tests get `@pytest.mark.unit`.
Unmarked tests still run (they land in the `unmarked` job), but marking is
better, because it keeps the fast lane fast.

---

## Making a change

`main` is protected: it takes merges from pull requests with passing checks,
not direct pushes. That applies to the maintainer too, so the process below is
the same one every change goes through.

1. Branch from `main`. Name it after the change (`fix-stats-poll-leak`), not
   after yourself.
2. Make the change, with a test that fails before it and passes after.
3. Push and open a PR. Say what problem it solves. The diff already shows
   what you did, so spend the words on why.
4. Wait for checks. The four test suites and the container build must pass.
   Codacy, SonarCloud, CodeQL and GitGuardian also report; they're advisory,
   but a legitimate finding should be addressed rather than ignored.
5. If it fixes an issue, put `fixes #123` in the PR body so it closes on merge.

PRs are squash-merged, so your branch's intermediate commits don't need to be
tidy. The PR title becomes the commit subject on `main`, so make that one good.

### Commit and PR messages

Imperative mood, sentence case, no trailing period:

```
Derive an accessible --brand-on-primary for custom brand colors (fixes #232)
Give every test its own database
Gate the tag pipeline on a green test suite
```

If the reasoning behind a change isn't obvious from the diff, put it in the
body. Several of this repo's more useful commit messages exist because the
non-obvious part was written down at the time.

---

## What's worth working on

Issues tagged [`good first issue`][gfi] are scoped to be self-contained. Beyond
those, bug reports with reproduction steps are always welcome, as is anything
that makes the remote-server setup less fiddly.

Two areas need care and are best discussed in an issue first:

- **Anything touching `core/crypto.py` or the master key.** Stored SSH private
  keys are encrypted with AES-256-GCM; a change that alters the key derivation
  or storage format can lock existing users out of their own servers.
- **Anything changing the SSH command surface.** The documented sudoers rules
  grant `quadlet-agent` a deliberately narrow set of commands. Adding a new
  remote command means every existing deployment has to update its sudoers file
  before upgrading.

[gfi]: https://github.com/karoltheguy/QuadletManager/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22

---

## Releases

Releases are cut by the maintainer by pushing a `v*.*.*` tag, which runs a
gated pipeline: version check → full test suite → container image → GitHub
Release. Nothing outward-facing is published until everything upstream is
green. See [docs/RELEASING.md](docs/RELEASING.md).

---

## Project layout

| Path | What lives there |
|---|---|
| `main.py` | FastAPI app entry point |
| `api/` | HTTP route handlers and WebSocket endpoints |
| `core/` | Database, crypto, config loading, event manager |
| `services/` | SSH connection pooling, sync and stats engines, quadlet parsing |
| `templates/` | Jinja templates; HTMX drives updates from the server |
| `static/` | Frontend assets (`static/vendor/` is generated by `npm ci`) |
| `tests/` | Test suite; `tests/e2e/` holds the Playwright tests |
| `docs/` | Architecture, setup, testing and release documentation |

[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) has the full picture, including
the API reference.

---

## Licence

By contributing, you agree that your contributions are licensed under the
GNU General Public License v3.0, the same licence as this project. See
[LICENSE.MD](LICENSE.MD).
