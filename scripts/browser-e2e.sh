#!/usr/bin/env bash
#
# Local driver for the browser (`e2e`) test suite.
#
# The tests need an app to point a browser at. This provisions a throwaway one
# -- scratch database in a temp directory, seeder, uvicorn on a free port -- runs
# pytest against it, and tears it all down on exit. Nothing is written to your
# working tree and no port is assumed to be free.
#
# The counterpart for the `podman` suite is scripts/podman-e2e.sh. The two
# deliberately keep their own copies of the app-provisioning code: this one
# seeds an empty database, that one seeds a live podman host into it, and a
# shared function would exist only to take a flag saying which. See docs/TESTING.md.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# The suite reads QM_APP_URL (tests/app_url.py). Exporting it for the whole
# pytest invocation is required, not just for the app process: the reachability
# gate in tests/conftest.py reads the same variable, and when the two disagree
# every browser test *skips* rather than fails. That is the failure this script
# exists to make impossible.
PYTHON="${QM_PYTHON:-python}"

log()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
die()  { printf '\033[31merror: %s\033[0m\n' "$*" >&2; exit 1; }

usage() {
    cat <<'EOF'
Usage: scripts/browser-e2e.sh <command> [pytest args]

  test [pytest args]   run `pytest -m e2e`; provisions a seeded scratch app
                       unless QM_APP_URL is already set
  app                  start the scratch app and print its URL, then wait
                       (ctrl-c to stop) -- for driving the UI by hand

Environment:
  QM_APP_URL       unset (auto-provisioned)  base URL of an already-running,
                   already-seeded app; when set, `test` uses it as-is
  QM_PYTHON        default `python`          interpreter to run the app with
  QUADLET_MASTER_KEY  default 64 zeroes      must match between seeder and app

Examples:
  scripts/browser-e2e.sh test
  scripts/browser-e2e.sh test tests/e2e/test_profile_menu.py -v
  QM_APP_URL=http://localhost:8000 scripts/browser-e2e.sh test
EOF
}

_APP_PID=""
_APP_DIR=""

cleanup() {
    [[ -n "$_APP_PID" ]] && kill "$_APP_PID" 2>/dev/null
    [[ -n "$_APP_DIR" ]] && rm -rf "$_APP_DIR"
    return 0
}
# INT and TERM as well as EXIT. A bash script killed by a signal it does not
# trap dies without running its EXIT trap, and `app` is documented as something
# you stop with ctrl-c -- which would otherwise leave uvicorn holding its port.
trap cleanup EXIT INT TERM

free_port() {
    "$PYTHON" -c 'import socket; s = socket.socket(); s.bind(("localhost", 0)); print(s.getsockname()[1]); s.close()'
}

wait_for_app() {
    local url="$1"
    for _ in $(seq 1 30); do
        if curl -sS -o /dev/null "$url/" 2>/dev/null; then
            return 0
        fi
        sleep 1
    done
    return 1
}

start_scratch_app() {
    _APP_DIR="$(mktemp -d)"
    export QUADLET_DB_PATH="$_APP_DIR/app.db"
    # The seeder and the app must share this, or the encrypted SSH key of the
    # seeded server cannot be decrypted and the server list renders broken.
    export QUADLET_MASTER_KEY="${QUADLET_MASTER_KEY:-$("$PYTHON" -c "print('0'*64)")}"

    log "seeding a scratch database in $_APP_DIR"
    PYTHONPATH=. "$PYTHON" -c "import asyncio, core.database as d; asyncio.run(d.init_db())"
    PYTHONPATH=. "$PYTHON" scripts/seed_test_db.py

    local port; port="$(free_port)"
    export QM_APP_URL="http://localhost:$port"

    # DEV_AUTO_LOGIN bypasses the login screen. The browser tests all start from
    # an authenticated dashboard, and docker-compose.test.yml sets it for the
    # same reason, so CI and this script agree on what the app looks like.
    DEV_AUTO_LOGIN=1 PYTHONPATH=. "$PYTHON" -m uvicorn main:app --port "$port" \
        > "$_APP_DIR/uvicorn.log" 2>&1 &
    _APP_PID=$!

    if ! wait_for_app "$QM_APP_URL"; then
        cat "$_APP_DIR/uvicorn.log" >&2
        die "the scratch app did not start; see the uvicorn log above"
    fi
    log "scratch app ready at $QM_APP_URL"
}

cmd_test() {
    if [[ -z "${QM_APP_URL:-}" ]]; then
        start_scratch_app
    else
        log "QM_APP_URL is already set; using the app at $QM_APP_URL"
    fi
    log "pytest -m e2e against $QM_APP_URL"
    PYTHONPATH=. "$PYTHON" -m pytest tests/ -m e2e "$@"
}

cmd_app() {
    [[ -n "${QM_APP_URL:-}" ]] && die "QM_APP_URL is already set to $QM_APP_URL; nothing to start"
    start_scratch_app
    log "ctrl-c to stop; the database and logs live in $_APP_DIR"
    wait "$_APP_PID"
}

case "${1:-}" in
    test) shift; cmd_test "$@" ;;
    app)  shift; cmd_app "$@" ;;
    ""|-h|--help|help) usage ;;
    *) usage; die "unknown command: $1" ;;
esac
