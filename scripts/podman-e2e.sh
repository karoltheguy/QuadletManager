#!/usr/bin/env bash
#
# Local driver for the `podman` test suite.
#
# Deliberately does NOT use compose. A podman-only dev machine has no compose
# provider at all (`podman compose` looks for a docker-compose binary that is
# not there), so every `docker compose -f docker-compose.test.yml` line in the
# docs is unrunnable there. Plain `podman run` works today. The compose profile
# in docker-compose.test.yml is kept for CI, where the app container has to
# reach this host by service name.
#
# Two targets, one test suite. See docs/TESTING.md.
#   A) container (default): localhost:2223, user `editor`. What CI runs.
#   B) loopback (opt-in):   localhost:22, user `quadlet-test`, native podman.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

IMAGE=quadletmanager-podman-host:local
CONTAINER=qm-podman-host
SSH_PORT=2223
TEST_KEY=tests/fixtures/test_key
LOOPBACK_USER=quadlet-test
SUDOERS_FILE=/etc/sudoers.d/quadlet-test

# Rootful podman for BOTH build and run, via one variable, for two reasons:
#
# 1. Image store. A rootless build puts the image in carol's store; `sudo podman
#    run` then looks in root's store and reports "image not found".
# 2. File capabilities. An unprivileged build cannot write security.capability
#    xattrs, so a rootless build strips cap_setuid from newuidmap. The image
#    still boots; only rootless podman *inside* it breaks. Dockerfile.podman-host
#    asserts this, so a rootless build now fails fast rather than mysteriously.
#
# Rootful is also simply the reliable choice here: it is the equivalent of
# Docker's privileged mode, whereas rootless podman-in-podman with systemd as
# PID 1 is the flakiest configuration available. Do not "simplify" this.
# Consequence worth knowing: the host container is therefore invisible to a
# plain `podman ps` run as your own user. Use `sudo podman ps`, or `$0 status`.
PODMAN="sudo podman"

log()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33mwarning: %s\033[0m\n' "$*" >&2; }
die()  { printf '\033[31merror: %s\033[0m\n' "$*" >&2; exit 1; }

usage() {
    cat <<'EOF'
Usage: scripts/podman-e2e.sh <command> [args]

Container target (default, matches CI):
  up                    build the image and start the podman host
  status                is the host reachable? (no sudo needed)
  down                  stop and remove the container
  test [pytest args]    run `pytest -m podman` against the selected target
  shell                 ssh into the target with the test key
  logs [args]           journalctl from inside the container

Loopback target (opt-in local fast path, needs sudo):
  setup-local           create the throwaway quadlet-test user and its access
  teardown-local        undo setup-local completely

Environment (read identically here and in tests/podman/conftest.py):
  QM_PODMAN_HOST   default localhost:2223   host:port of the target
  QM_PODMAN_USER   default editor           ssh user
  QM_PODMAN_KEY    default tests/fixtures/test_key
EOF
}

# --------------------------------------------------------------------------
# Container target
# --------------------------------------------------------------------------

cmd_up() {
    # Ask for the password up front. Sudo's credential cache is 5 minutes by
    # default and a cold Fedora build can outrun it, so without this the build
    # succeeds and then `podman run` re-prompts partway through the script --
    # which looks like a hang or a crash rather than a password prompt.
    #
    # `up` and `down` are the only subcommands that need root at all. The
    # iteration loop (test, shell, logs) never does.
    if ! sudo -n true 2>/dev/null; then
        log "Rootful podman is required to build and run the host (see the comment above)"
        sudo -v || die "cannot obtain sudo; try the loopback target instead: sudo $0 setup-local"
    fi

    log "Building $IMAGE (rootful, see comment in this script)"
    $PODMAN build -f Dockerfile.podman-host -t "$IMAGE" .

    if $PODMAN container exists "$CONTAINER" 2>/dev/null; then
        log "Removing the previous $CONTAINER"
        $PODMAN rm -f "$CONTAINER" >/dev/null
    fi

    log "Starting $CONTAINER on port $SSH_PORT"
    # --privileged + /dev/fuse: required to run podman inside this container.
    #   Same accepted, test-only risk as remote-systemd (see #159).
    # --cgroupns=private: let the nested systemd own its own cgroup namespace.
    #   Deliberately no /sys/fs/cgroup bind mount. On a cgroup v2 host that
    #   read-only bind prevents nested podman from delegating cgroups.
    $PODMAN run -d --name "$CONTAINER" \
        --privileged --cgroupns=private --device /dev/fuse \
        --security-opt seccomp=unconfined --security-opt label=disable \
        --tmpfs /run --tmpfs /tmp \
        -p "${SSH_PORT}:22" \
        "$IMAGE" /usr/sbin/init >/dev/null

    wait_ready
}

# Readiness, in the same order the CI gate uses: systemd up, ssh answering,
# rootless podman actually usable. Each stage failing means something different.
wait_ready() {
    log "Waiting for systemd"
    for _ in $(seq 1 60); do
        state="$($PODMAN exec "$CONTAINER" systemctl is-system-running 2>/dev/null || true)"
        case "$state" in
            running) break ;;
            degraded)
                # The image masks the container-impossible kernel mounts, so
                # degraded now means something genuinely failed.
                $PODMAN exec "$CONTAINER" systemctl --failed --no-pager || true
                die "systemd came up degraded; see the failed units above"
                ;;
        esac
        sleep 2
    done
    [ "${state:-}" = "running" ] || die "systemd did not reach running in 120s"

    log "Waiting for sshd on $SSH_PORT"
    for _ in $(seq 1 30); do
        if ssh_target true 2>/dev/null; then break; fi
        sleep 2
    done
    if ! ssh_target true 2>/dev/null; then
        # Re-run with stderr visible; a silent retry loop hides the one line
        # that says whether this is a refused connection or a rejected key.
        ssh_target true || true
        die "cannot ssh to $(target_user)@localhost:$SSH_PORT"
    fi

    log "Checking rootless podman as editor"
    if ! ssh_target 'podman info >/dev/null 2>&1'; then
        ssh_target 'podman info' || true
        die "rootless podman is not usable (linger? newuidmap filecaps?)"
    fi

    # The build-time preload should have populated both stores. If the load unit
    # failed, fall back to a live pull rather than failing the whole run.
    if ! ssh_target 'podman image exists quay.io/quay/busybox:latest'; then
        warn "preloaded image missing from the rootless store; pulling"
        ssh_target 'podman pull quay.io/quay/busybox:latest'
    fi
    if ! ssh_target 'sudo podman image exists quay.io/quay/busybox:latest'; then
        warn "preloaded image missing from the rootful store; pulling"
        ssh_target 'sudo podman pull quay.io/quay/busybox:latest'
    fi

    log "Ready: $($PODMAN exec "$CONTAINER" cat /etc/podman-version)"

    # Say this out loud. The container runs under ROOTFUL podman, and rootful
    # and rootless have entirely separate container stores, so a plain
    # `podman ps` as your own user shows nothing at all and the host looks like
    # it failed to start.
    cat <<EOF

The host runs under rootful podman, so your own \`podman ps\` will NOT show it.
  see it:     sudo podman ps
  check it:   $0 status
  run tests:  $0 test
EOF
}

cmd_status() {
    # Deliberately does not use sudo. Reachability over SSH is the thing that
    # actually matters to the tests, and checking it needs no password.
    local host port
    host="$(target_host)"; port="$(target_port)"

    if ! (exec 3<>"/dev/tcp/$host/$port") 2>/dev/null; then
        echo "DOWN: nothing listening on $host:$port"
        echo "  start it with: sudo $0 up"
        return 1
    fi
    echo "port $host:$port is open"

    if ! ssh_target true 2>/dev/null; then
        echo "DOWN: port is open but ssh failed"
        ssh_target true || true
        return 1
    fi

    echo "UP: $(ssh_target 'podman --version') as $(ssh_target whoami)"
    echo "rootless podman inside: $(ssh_target 'podman info --format "{{.Host.Security.Rootless}}"' 2>/dev/null)"
    echo
    echo "Note: this container runs under rootful podman. Your own \`podman ps\`"
    echo "will not list it; use \`sudo podman ps\`."
}

cmd_down() {
    log "Removing $CONTAINER"
    $PODMAN rm -f "$CONTAINER" 2>/dev/null || true
}

cmd_logs() {
    # Over SSH rather than `podman exec`, for two reasons: it needs no root on
    # the dev machine, and it works unchanged against the loopback target.
    # Falls back to an unprivileged journalctl because the loopback target's
    # sudoers allowlist deliberately permits only `journalctl -u *`.
    local args="${*:---no-pager -n 200}"
    ssh_target "sudo journalctl $args 2>/dev/null || journalctl $args"
}

# --------------------------------------------------------------------------
# Target-agnostic helpers
# --------------------------------------------------------------------------

target_host() { echo "${QM_PODMAN_HOST:-localhost:2223}" | cut -d: -f1; }
target_port() {
    local hp="${QM_PODMAN_HOST:-localhost:2223}"
    case "$hp" in *:*) echo "${hp##*:}" ;; *) echo 22 ;; esac
}
target_user() { echo "${QM_PODMAN_USER:-editor}"; }
target_key()  { echo "${QM_PODMAN_KEY:-$TEST_KEY}"; }

_KEY_COPY=""

# ssh refuses a private key that is readable by group or other, and falls back
# to password auth. The committed fixture is mode 644 because git records only
# the executable bit, so every fresh clone hits this. Copy it to a private
# temp file rather than chmod-ing a file in the developer's working tree.
#
# MUST be called as a plain statement, never as `$(ensure_key_copy)`. Command
# substitution runs the function in a subshell, so the assignment below would be
# discarded and, worse, the EXIT trap would fire when that subshell ended and
# delete the key before ssh ever opened it. The symptom is
# "Identity file /tmp/tmp.XXXX not accessible" followed by a permission-denied,
# which reads like a broken key rather than a shell scoping mistake.
ensure_key_copy() {
    if [ -z "$_KEY_COPY" ] || [ ! -f "$_KEY_COPY" ]; then
        _KEY_COPY="$(mktemp)"
        chmod 600 "$_KEY_COPY"
        cat "$(target_key)" > "$_KEY_COPY"
        trap 'rm -f "$_KEY_COPY"' EXIT
    fi
}

ssh_target() {
    # BatchMode=yes and publickey-only are not optional. Without them, a key
    # that ssh declines to use turns into an interactive password prompt --
    # and because DISPLAY is set, ssh pops a *graphical* one, once per retry
    # in the readiness loop, asking for the container account's password.
    ensure_key_copy
    ssh -i "$_KEY_COPY" -p "$(target_port)" \
        -o BatchMode=yes \
        -o PreferredAuthentications=publickey \
        -o PasswordAuthentication=no \
        -o KbdInteractiveAuthentication=no \
        -o StrictHostKeyChecking=no \
        -o UserKnownHostsFile=/dev/null \
        -o LogLevel=ERROR \
        "$(target_user)@$(target_host)" "$@"
}

cmd_shell() {
    log "ssh $(target_user)@$(target_host):$(target_port)"
    ssh_target
}

cmd_test() {
    log "pytest -m podman against $(target_user)@$(target_host):$(target_port)"
    PYTHONPATH=. python -m pytest tests/ -m podman "$@"
}

# --------------------------------------------------------------------------
# Loopback target
# --------------------------------------------------------------------------

# A dedicated throwaway user, never the developer's own account: the global-scope
# tests write to the real /etc/containers/systemd on this machine.
cmd_setup_local() {
    [ "$(id -u)" -eq 0 ] || die "setup-local must run as root (sudo $0 setup-local)"

    log "Preparing the loopback target"
    local changed=()

    if id "$LOOPBACK_USER" >/dev/null 2>&1; then
        echo "user $LOOPBACK_USER already exists, leaving it alone"
    else
        useradd -m -s /bin/bash "$LOOPBACK_USER"
        changed+=("created user $LOOPBACK_USER")
    fi

    local home; home="$(getent passwd "$LOOPBACK_USER" | cut -d: -f6)"

    # Linger, so /run/user/<uid> exists for a non-interactive SSH session.
    # Without it every rootless command returns nothing at all.
    if [ -e "/var/lib/systemd/linger/$LOOPBACK_USER" ]; then
        echo "linger already enabled"
    else
        loginctl enable-linger "$LOOPBACK_USER"
        changed+=("enabled linger for $LOOPBACK_USER")
    fi

    install -d -m 700 -o "$LOOPBACK_USER" -g "$LOOPBACK_USER" "$home/.ssh"
    local authkeys="$home/.ssh/authorized_keys"
    local pubkey; pubkey="$(cat "$REPO_ROOT/$TEST_KEY.pub")"
    if [ -f "$authkeys" ] && grep -qF "$pubkey" "$authkeys"; then
        echo "test key already authorized"
    else
        echo "$pubkey" >> "$authkeys"
        changed+=("appended the test key to $authkeys")
    fi
    chown "$LOOPBACK_USER:$LOOPBACK_USER" "$authkeys"
    chmod 600 "$authkeys"

    # The narrow allowlist from README.MD / docs/SETUP.MD rather than
    # NOPASSWD:ALL. This makes the loopback target double as the only check that
    # the documented sudoers policy is actually sufficient to run the app.
    cat > "$SUDOERS_FILE" <<EOF
$LOOPBACK_USER ALL=(ALL) NOPASSWD: /usr/bin/systemctl daemon-reload
$LOOPBACK_USER ALL=(ALL) NOPASSWD: /usr/bin/systemctl start *
$LOOPBACK_USER ALL=(ALL) NOPASSWD: /usr/bin/systemctl stop *
$LOOPBACK_USER ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart *
$LOOPBACK_USER ALL=(ALL) NOPASSWD: /usr/bin/systemctl status *
$LOOPBACK_USER ALL=(ALL) NOPASSWD: /usr/bin/journalctl -u *
$LOOPBACK_USER ALL=(ALL) NOPASSWD: /usr/bin/tee /etc/containers/systemd/*
$LOOPBACK_USER ALL=(ALL) NOPASSWD: /usr/bin/podman stats *
EOF
    chmod 440 "$SUDOERS_FILE"
    visudo -cf "$SUDOERS_FILE" >/dev/null || die "generated an invalid $SUDOERS_FILE"
    changed+=("wrote $SUDOERS_FILE")

    log "Done. Changes made:"
    if [ "${#changed[@]}" -eq 0 ]; then
        echo "  (none, already set up)"
    else
        printf '  - %s\n' "${changed[@]}"
    fi
    cat <<EOF

Undo everything with:
  sudo $0 teardown-local

Run the suite against this target with:
  QM_PODMAN_HOST=localhost:22 QM_PODMAN_USER=$LOOPBACK_USER \\
    PYTHONPATH=. python -m pytest tests/ -m podman -v
EOF
}

cmd_teardown_local() {
    [ "$(id -u)" -eq 0 ] || die "teardown-local must run as root (sudo $0 teardown-local)"

    log "Undoing the loopback target"
    if id "$LOOPBACK_USER" >/dev/null 2>&1; then
        loginctl disable-linger "$LOOPBACK_USER" 2>/dev/null || true
        # Stop the lingering user manager before removing the account, or
        # userdel refuses on "user is currently used by process".
        loginctl terminate-user "$LOOPBACK_USER" 2>/dev/null || true
        sleep 1
        userdel -r "$LOOPBACK_USER" 2>/dev/null || warn "userdel failed; check $LOOPBACK_USER by hand"
        echo "  - removed user $LOOPBACK_USER and its home"
    else
        echo "  - user $LOOPBACK_USER already absent"
    fi

    if [ -f "$SUDOERS_FILE" ]; then
        rm -f "$SUDOERS_FILE"
        echo "  - removed $SUDOERS_FILE"
    fi

    # The loopback target writes global-scope units to the real machine. If a
    # run crashed mid-way they are still here. Report, never auto-delete.
    local leaked
    leaked="$(ls /etc/containers/systemd/ 2>/dev/null | grep '^e2e-' || true)"
    if [ -n "$leaked" ]; then
        warn "leftover e2e- units in /etc/containers/systemd:"
        echo "$leaked" | sed 's/^/      /'
        warn "remove them by hand, then run: systemctl daemon-reload"
    fi
}

# --------------------------------------------------------------------------

case "${1:-}" in
    up)             shift; cmd_up "$@" ;;
    status)         shift; cmd_status "$@" ;;
    down)           shift; cmd_down "$@" ;;
    test)           shift; cmd_test "$@" ;;
    shell)          shift; cmd_shell "$@" ;;
    logs)           shift; cmd_logs "$@" ;;
    setup-local)    shift; cmd_setup_local "$@" ;;
    teardown-local) shift; cmd_teardown_local "$@" ;;
    -h|--help|help|"") usage ;;
    *)              usage; exit 1 ;;
esac
