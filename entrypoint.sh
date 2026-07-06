#!/bin/sh
set -e

# Volumes populated by an older image (or first created by Podman) may still
# be owned by root. Reconcile ownership on every start so upgrades never
# leave appuser unable to write to /data (see #162).
chown -R appuser:appuser /data

exec gosu appuser "$@"
