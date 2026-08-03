# Sudo permissions

QuadletManager's root surface on a managed server has two halves, and they are
supposed to describe the same set of commands:

* **What is granted.** The sudoers allowlist, which ships as
  `deploy/quadlet-manager.sudoers`.
* **What the app needs.** Every command the app actually issues under `sudo`,
  with its call site. That list is in this file, below.

The two now agree.
`tests/podman/test_sudo_policy.py` is what keeps them that way, by asking a
real host with `sudo -n -l` whether the grant list permits every entry in the
need list.

Rootless (user) scope needs no sudo at all. Everything here is global scope.

## The grant list

**`deploy/quadlet-manager.sudoers`.** Not reproduced here, because a copy in
this file would be one more thing to keep in step. It is a real installable
file with `%AGENT%` where the account name goes, and everything that installs
the allowlist reads it:

| Installer | Substitutes | Installs to |
|---|---|---|
| a human, following `docs/SETUP.MD` | `quadlet-agent` | `/etc/sudoers.d/quadlet-manager` |
| `scripts/podman-e2e.sh setup-local` | `$LOOPBACK_USER` | `/etc/sudoers.d/quadlet-test` |
| `Dockerfile.podman-host` | `narrow` | `/etc/sudoers.d/quadlet-manager` |

`docs/SETUP.MD` reproduces the rules in prose, because someone setting up a
server should be able to read them without opening a second file. That copy is
the only one, and `tests/test_sudo_allowlist_sync.py` fails if it drifts from
the original. The same test fails if an installer stops reading the file and
starts embedding the rules again.

It got this way on purpose. The rules used to be written out in four places,
which is why they could drift and why a sync guard was needed to notice. Three
of those four were installers that never needed the text at all, only a file to
substitute into.

## The need list

Every command the app runs under `sudo`, one row each, in the form the policy
test probes. The probe is a real command line with placeholder arguments;
`sudo -n -l --` only answers whether the policy permits it and runs nothing, so
the placeholders never have to exist.

Keep the probe faithful to what runs. `stats_engine._build_podman_commands`
returns a bare `sudo podman stats`, which the `podman stats *` rule does not
match, but that string is only ever a prefix: the arguments are appended before
it executes. Probing the prefix alone reports a denial that does not happen.

<!-- BEGIN NEED LIST -->

| Probe | Call site | Notes |
|---|---|---|
| `/usr/bin/systemctl daemon-reload` | `services/systemd_manager.py` `systemctl_action` | after every write |
| `/usr/bin/systemctl start e2e-probe.service` | `services/systemd_manager.py` `systemctl_action` | |
| `/usr/bin/systemctl stop e2e-probe.service` | `services/systemd_manager.py` `systemctl_action` | |
| `/usr/bin/systemctl restart e2e-probe.service` | `services/systemd_manager.py` `systemctl_action` | |
| `/usr/bin/systemctl status e2e-probe.service` | `services/systemd_manager.py` `systemctl_action` | |
| `/usr/bin/journalctl -u e2e-probe.service` | `scripts/podman-e2e.sh` logs | |
| `/usr/bin/tee /etc/containers/systemd/e2e-probe.container` | `services/remote_fs.py` `write_remote_file` | the only write path |
| `/usr/bin/podman stats --no-stream --format json e2e-probe` | `services/stats_engine.py` `_build_podman_commands` plus the caller | prefix plus appended args |
| `/usr/bin/systemctl show e2e-probe.service --property=Id,LoadState,ActiveState,SubState,NRestarts` | `services/systemd_manager.py` `build_unit_state_command`, reused by `services/stats_engine.py` | unit state, Monitor |
| `/usr/bin/find /etc/containers/systemd -type f -maxdepth 1` | `services/tree_scanner.py` | listing the tree |
| `/usr/bin/cat /etc/containers/systemd/e2e-probe.container` | `api/routes.py` | opening a quadlet |
| `/usr/bin/stat -c %Y /etc/containers/systemd/e2e-probe.container` | `api/routes.py` | single path, save-time change check |
| `/usr/bin/stat -c '%n %Y' /etc/containers/systemd/e2e-probe.container` | `services/sync_engine.py` | batch form, several paths at once |
| `/usr/bin/mkdir -p /etc/containers/systemd` | `api/routes.py` | first write to an empty host |
| `/usr/bin/rm -f /etc/containers/systemd/e2e-probe.container` | `api/routes.py` | deleting a quadlet |
| `/usr/bin/podman ps --format json` | `services/stats_engine.py` `_build_podman_commands` | Monitor container list |
| `/usr/bin/podman pod start e2e-probe` | `api/routes.py` | pod actions |
| `/usr/bin/podman pod stop e2e-probe` | `api/routes.py` | |
| `/usr/bin/podman pod restart e2e-probe` | `api/routes.py` | |
| `/usr/bin/journalctl -u e2e-probe.service -f -n 100` | `api/sockets.py` `stream_logs_over_websocket` | live log streaming |

<!-- END NEED LIST -->

## Deliberately not granted

| Probe | Call site | Notes |
|---|---|---|
| `/usr/bin/podman exec -it e2e-probe /bin/sh` | `api/sockets.py` `_build_exec_command` | the terminal tab |

Everything else in the need list is root-equivalent by way of a unit file the
agent itself writes: it lands on disk under a name, and it only takes effect
after a `daemon-reload`, so there is an artifact and an audit trail for what
ran. `podman exec -it` is a different shape of risk rather than the same one
widened. It is interactive root inside any container the app can see, reached
over a websocket, and it leaves no such artifact behind. In `api/sockets.py`
`_build_exec_command`, the container name is regex-validated, but the command
string handed to the shell is only quoted, not restricted to an allowlist. For
that reason the terminal tab stays user-scope-only for now, and granting it in
global scope is left as a separate decision, to be made on its own merits
rather than folded into closing #289.

Twelve of those used to be the gap: a server built to the published docs could
write a quadlet file it could not then read back, and start a unit whose state
it could not show. See `docs/TESTING_TODO.md` section 3 for the full account of
how this was found.

Two rows are wider than #289 recorded, because #289 was written from the
loopback run and the WebSocket paths never got exercised there. Both live in
`api/sockets.py`, which builds its command for `conn.create_process` directly
instead of going through `pool.execute_command(use_sudo=True)`, so a search for
`use_sudo` does not find them. Asked of a real sudo on fedora:43 with the grant
list above installed:

* **Log streaming** appends `-f` and either `-n 100` or `--since`, and is
  **permitted**. A trailing `*` in a sudoers rule matches across argument
  boundaries, so `journalctl -u *` covers `-u unit -f -n 100` as well. Worth
  recording because it is easy to assume the opposite and widen the rule for
  no reason.
* **The terminal** is denied, and deliberately so. See "Deliberately not
  granted" above.

## Adding a command that needs sudo

1. Add a row to the need list above, with the probe as it will really run.
2. Run `pytest tests/podman/test_sudo_policy.py -m podman` against a host. If
   the new row is denied, the allowlist needs a rule for it.
3. If it does, add the rule to `deploy/quadlet-manager.sudoers` and then to the
   copy in `docs/SETUP.MD`. Nothing else needs touching: the installers
   substitute into that file rather than repeating it.
   `tests/test_sudo_allowlist_sync.py` fails until the two agree, and it runs
   in the `unit` job, so this is caught without a podman host.

Scope every path rule to `/etc/containers/systemd/*`. Keep doing this: it is
still the right habit, and it still narrows the surface a compromised agent
account could reach. But see the next section before you rely on it for
anything more than that.

## The glob is not confinement

It is tempting to read `/etc/containers/systemd/*` as a sandbox: the rule
looks like it can only ever touch files under that one directory. It can't.
sudo matches command *arguments* against that pattern with fnmatch, and it
does so without `FNM_PATHNAME`, the flag that would stop `*` from matching
`/`. Without it, `*` matches path separators exactly as happily as any other
character, so `/etc/containers/systemd/../../etc/shadow` matches the rule
just as cleanly as `/etc/containers/systemd/web.container` does. A `..`
segment in a caller-supplied path walks straight back out of the directory
the rule was written to pin.

What actually confines a caller-supplied path before it reaches a sudo'd
command is `services.remote_fs.ensure_within_quadlet_dir`, called from every
route that accepts one (`fetch_file`, `save_file`, `delete_file`,
`create_new_quadlet`) before the corresponding shell command is built. It
normalizes the path and requires that its parent directory equal the quadlet
directory for the scope exactly, which rejects traversal, the directory
itself, subdirectories, and string-prefix siblings like
`/etc/containers/systemd-evil` in one comparison. See
`tests/test_quadlet_path_confinement.py` and
`tests/test_route_path_confinement.py` for the cases it covers.

That check is lexical, and it is worth being honest about what it does not
cover: if a symlink is already planted inside the quadlet directory on the
remote host, this check has no way to see where the link actually points,
because it never inspects the remote filesystem. Catching that would need a
check performed on the remote side, not here.
