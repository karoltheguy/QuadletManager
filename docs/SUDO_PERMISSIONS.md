# Sudo permissions

The one place that records both halves of QuadletManager's root surface on a
managed server:

* **What the docs grant.** The sudoers allowlist published in `README.MD` and
  `docs/SETUP.MD`, and written by `scripts/podman-e2e.sh setup-local`.
* **What the app needs.** Every command the app actually issues under `sudo`,
  with its call site.

Those two lists are supposed to be the same list. Today they are not, which is
[issue #289](https://github.com/karoltheguy/QuadletManager/issues/289): global
scope does not work on a server set up exactly as the docs describe.

Both blocks below are parsed by tests. Edit them here, not in the copies.

* `tests/test_sudo_allowlist_sync.py` pins the grant list to its three copies,
  so they cannot drift apart.
* `tests/podman/test_sudo_policy.py` asks a real host, with `sudo -n -l`,
  whether the grant list permits every entry in the need list.

Rootless (user) scope needs no sudo at all. Everything here is global scope.

## The grant list

Exactly what `README.MD` section 2, `docs/SETUP.MD` section 3 and
`scripts/podman-e2e.sh` install. `%AGENT%` stands for the account the app SSHes
in as: `quadlet-agent` in the docs, `$LOOPBACK_USER` in the script.

This is a record of what is published today, not a recommendation. It is known
to be insufficient; see the need list below.

```sudoers
%AGENT% ALL=(ALL) NOPASSWD: /usr/bin/systemctl daemon-reload
%AGENT% ALL=(ALL) NOPASSWD: /usr/bin/systemctl start *
%AGENT% ALL=(ALL) NOPASSWD: /usr/bin/systemctl stop *
%AGENT% ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart *
%AGENT% ALL=(ALL) NOPASSWD: /usr/bin/systemctl status *
%AGENT% ALL=(ALL) NOPASSWD: /usr/bin/journalctl -u *
%AGENT% ALL=(ALL) NOPASSWD: /usr/bin/tee /etc/containers/systemd/*
%AGENT% ALL=(ALL) NOPASSWD: /usr/bin/podman stats *
```

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
| `/usr/bin/podman exec -it e2e-probe /bin/sh` | `api/sockets.py` `_build_exec_command` | the terminal tab |

<!-- END NEED LIST -->

Twelve of those are the gap. A server built to the published docs can write a
quadlet file it cannot then read back, and start a unit whose state it cannot
show. See `docs/TESTING_TODO.md` section 3 for the full account of how this was
found.

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
* **The terminal** runs `podman exec -it`, and is **denied**. Nothing in the
  grant list covers it; `podman stats *` does not match a different
  subcommand. So the terminal tab does not work in global scope on a server
  built to the documentation, which #289 does not yet mention.

## Adding a command that needs sudo

1. Add a row to the need list above, with the probe as it will really run.
2. Run `pytest tests/podman/test_sudo_policy.py -m podman` against a host. If
   the new row is denied, the grant list needs a rule for it.
3. If it does, add the rule to the grant list above **and** to `README.MD`,
   `docs/SETUP.MD` and `scripts/podman-e2e.sh`. `tests/test_sudo_allowlist_sync.py`
   fails until all four agree, and it runs in the `unit` job, so this is caught
   without a podman host.

Scope every path rule to `/etc/containers/systemd/*`. A sudoers `*` does not
match `/`, so that pattern cannot reach a subdirectory.
