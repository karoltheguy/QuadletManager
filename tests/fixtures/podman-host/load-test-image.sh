#!/usr/bin/env bash
# Load the build-time-preloaded test image into both podman image stores.
#
# Rootless and rootful podman keep separate stores, so an image loaded as root
# is invisible to `editor` and vice versa. The quadlet fixtures run in both
# scopes, so both need it.
#
# Failure here is not fatal to the boot: scripts/podman-e2e.sh and the CI
# readiness gate fall back to a live `podman pull`. Exiting non-zero would only
# make `systemctl is-system-running` report degraded and mask real problems.
set -uo pipefail

ARCHIVE=/opt/test-image.tar

if [[ ! -f "$ARCHIVE" ]]; then
    echo "no $ARCHIVE to load; tests will fall back to a network pull" >&2
    exit 0
fi

echo "loading $ARCHIVE into the rootful store"
podman load -i "$ARCHIVE" || echo "rootful load failed" >&2

echo "loading $ARCHIVE into the rootless store for editor"
runuser -u editor -- env XDG_RUNTIME_DIR=/run/user/1000 \
    podman load -i "$ARCHIVE" || echo "rootless load failed" >&2

exit 0
