# Testing follow-ups

Open items left by the `podman` suite work. Each was found by running the suite
against a real host, locally or in CI, and each was deliberately left undone
rather than overlooked, with the reason recorded.

Order is roughly by how much it matters, not by effort.

---

## 1. Keeping the two targets agreeing

**Status: verified on `1045783`. Standing obligation, not an open defect.**

The design rule is that both targets produce the same result on the same
commit. That went unchecked through twelve CI rounds, during which the image
gained a `PAMName=` drop-in on `user@.service` with an explicit
`Environment=XDG_RUNTIME_DIR=/run/user/%i`, a replaced `/etc/pam.d/sshd` (its
account stage only, `pam_systemd` kept), a replaced `/etc/pam.d/sudo`, an
`/etc/ssh/sshd_config.d` drop-in asserted through `sshd -G`, and serial
execution. For a while the two targets had never been compared on any commit
after the first round.

They have now, on `1045783`, and they agree exactly:

| | Result |
|---|---|
| CI, run 30673858953 | 37 passed, 1029 deselected, 1 xfailed, 64.65s |
| Local rootful podman | 37 passed, 1029 deselected, 1 xfailed, 60.68s |

The host was also checked afterwards and was clean: no quadlet files in either
scope, no containers, no pods, no failed units, `systemctl is-system-running`
returning `running`.

**Re-verify after any change to `Dockerfile.podman-host`.** The recipe is
`sudo ./scripts/podman-e2e.sh up`, then `pytest tests/ -m podman`; add
`QM_APP_URL` and a seeded instance for the browser journeys, per
[TESTING.md](TESTING.md#running-the-browser-journeys). Until that runs, "it
works locally" is a statement about whichever image you last built.

---

## 2. Why PAM fails inside this container is still unknown

**Status: every fix so far treats a symptom.**

Three separate failures on this host, all reporting PAM_AUTHINFO_UNAVAIL out of
the account stage: the user manager (`user@1000.service`, status=224/PAM), then
sshd (`Access denied for user editor by PAM account configuration`), then sudo.
Each became visible only once the previous one was fixed. All three happen on a
GitHub runner and none happen under local rootful podman, on the same
Dockerfile. What actually causes that difference was never established.

Ruled out by direct test, on the runner, and recorded here so nobody spends the
round again:

* sssd, faillock and sepermit: not in fedora:43's `local` authselect profile at
  all, so they were never in the stack.
* nss-systemd in group lookups: with `group: files` in place, `getent group
  editor` returned rc=0 in 0.001s and sshd failed identically (run
  30663777881).

Two opt-outs remain, `PAMName=` on `user@.service` and the replaced
`/etc/pam.d/sudo`, and **both were tested on the runner and both are still
load-bearing**:

* Removing `/etc/pam.d/sudo` failed the *build* (run 30673576555), at the layer
  that asserts `runuser -u editor -- sudo -n true`.
* Removing the `user@.service` drop-in put systemd into `degraded` with
  `user@1000.service loaded failed failed`, one second into the readiness gate
  (run 30673677574).

So the theory they were added under is wrong: fixing sshd's account stage did
not make either redundant, and the three failures do not share one fixable
cause the way they appeared to.

**The useful finding is where sudo failed.** It reproduces at *build* time, in
a plain `docker build` layer, before systemd, sshd, linger, any drop-in, or any
privileged runtime flag exists. Whatever the cause is, it belongs to the base
image and the runner rather than to anything running inside the container or to
how the container is started. That rules out every explanation needing a
session, a logind registration or a container runtime setting, which is most of
what was on the list, and it is the first *positive* constraint on this rather
than another elimination.

It also makes the next experiment cheap. A plain
`docker run fedora:43` on a runner, with nothing but `useradd` and a NOPASSWD
sudoers line, should reproduce it in isolation, with no part of this image
involved.

Consequence to plan for: a runner image change can move this in either
direction without warning. The build-time assertions in
`Dockerfile.podman-host` are what would catch it.

---

## 3. The documented sudoers allowlist is not sufficient for global scope

**Resolved.** The gap this section describes is closed: the allowlist gained
the eleven rules the probe below found missing, the strict `xfail` on
`tests/podman/test_sudo_policy.py` has been removed now that the policy and
the app agree, and `podman exec` remains deliberately excluded rather than
granted. The account below is kept as the historical record of the run that
found the gap and is not updated to match.

**Status: run on 2026-08-01. The target works; what it found is an app bug.**

**Update, 2026-08-02.** The two tests this section asked for now exist, so the
gap is pinned rather than only written down. The list of what the app runs
under sudo moved to [SUDO_PERMISSIONS.md](SUDO_PERMISSIONS.md); the table below
is kept as the record of the run that found it.

The allowlist itself is no longer written out four times. It ships as
`deploy/quadlet-manager.sudoers`, with `%AGENT%` where the account name goes,
and every installer substitutes into that file: `scripts/podman-e2e.sh` for the
loopback target, `Dockerfile.podman-host` for the container target's new
`narrow` account, and the reader of `docs/SETUP.MD` for a real server.
`README.MD` links to `docs/SETUP.MD` rather than repeating it, leaving one
prose copy. `tests/test_sudo_allowlist_sync.py` pins that copy to the original
in the `unit` job, and fails if an installer goes back to embedding rules.

`tests/podman/test_sudo_policy.py` probes a real sudo as the `narrow` account
and is `xfail(strict=True)` until the policy and the app agree. The fix itself,
and the narrowing of `editor` described at the end of this section, are still
open.

Probing a real sudo also found two commands this table missed, both in
`api/sockets.py`, which embeds `sudo` in the string it hands to
`conn.create_process` instead of passing `use_sudo=True`. Live log streaming
(`journalctl -u <unit> -f -n 100`) turns out to be **permitted**, because a
trailing sudoers `*` matches across argument boundaries. The terminal
(`podman exec -it`) is **not**, so that tab is broken in global scope too.

The loopback target was run for the first time, on Fedora 44 with podman 5.8.4:
`31 passed, 6 failed, 1029 deselected, 1 xfailed`. Three failures are the
browser journeys, which ran against a dev instance that had no Podman Host row
and are not evidence of anything. The three that matter are all one cause.

`setup-local` grants exactly the allowlist shipped in
`deploy/quadlet-manager.sudoers`, which is the entire point of the target. At
the time of this run that file was eight lines, and the app needed
considerably more than that. Asked directly, with `sudo -n -l`, that policy
answers:

| Command the app issues under sudo | Allowed? | Call site |
|---|---|---|
| `tee /etc/containers/systemd/*` | yes | `services/remote_fs.py:58` |
| `systemctl daemon-reload` | yes | `services/systemd_manager.py:137` |
| `systemctl start/stop/restart/status <unit>` | yes | `services/systemd_manager.py:137` |
| `journalctl -u <unit>` | yes | `scripts/podman-e2e.sh` logs |
| `podman stats --no-stream --format json <names>` | yes | `services/stats_engine.py:331` |
| `systemctl show <units> --property=...` | **no** | `services/systemd_manager.py:99`, `services/stats_engine.py:288` |
| `find /etc/containers/systemd -type f -maxdepth 1` | **no** | `services/tree_scanner.py:51` |
| `cat <path>` | **no** | `api/routes.py:571` |
| `stat -c %Y <path>` | **no** | `api/routes.py:625`, `services/sync_engine.py:123` |
| `mkdir -p /etc/containers/systemd` | **no** | `api/routes.py:796` |
| `rm -f <path>` | **no** | `api/routes.py:1675` |
| `podman ps --format json` | **no** | `services/stats_engine.py:231` |
| `podman pod start/stop/restart <pod>` | **no** | `api/routes.py:733` |

So a server set up strictly by the book has a global scope that cannot list its
quadlets, open one, save one, create one, delete one, report unit state, or show
anything in Monitor. It can write a file it cannot then read back, and start a
unit it cannot show you. Verify the line numbers before citing them; they were
correct on 2026-08-01.

`podman stats` is worth one note, because it looks like a fourteenth denial and
is not. `_build_podman_commands` returns a bare `sudo podman stats`, which the
`podman stats *` line does not match, but the string is only ever a prefix:
`stats_engine.py:331` appends `--no-stream --format json <names>` before it
runs. Probing the prefix alone gives a false positive.

**Why twelve CI rounds never saw this.** `Dockerfile.podman-host:82` grants
`editor ALL=(ALL) NOPASSWD:ALL`. The container target cannot detect a
too-narrow allowlist in principle, no matter how many times it runs, because it
grants everything. That is precisely the gap this target was written to close,
and it closed it on the first run.

**Consequence for the "both targets agree" rule** in
[TESTING.md](TESTING.md#the-two-targets): as things stand they cannot, and
should not be expected to. The loopback target is the stricter environment, not
an equivalent one. The rule becomes true again only if
`Dockerfile.podman-host` is narrowed to the same allowlist, which is the change
that would put this check in CI. Do that *after* the policy and the app agree,
not before, or CI goes red on a known defect.

**Second, smaller finding.** `test_test_image_is_preloaded[global]` reports
`busybox missing`, but that is a masked sudo denial:
`podman image exists ... && echo present || echo missing` turns sudo's non-zero
exit into `missing`. Underneath it there is a real gap anyway. The container
target preloads the image into both stores through `load-test-image.service`;
`setup-local` does nothing equivalent, so the user-scope tests passed only
because podman pulled from quay.io during the run. The loopback target
therefore needs a network where the container target does not.

**What is now verified:** the target itself works. Rootless scope is fully
green on a real machine, and the safety rails held: nothing was written outside
`e2e-` names, and `/etc/containers/systemd` was empty before and after. Note
that the global-scope writes never got far enough to test the teardown guard
properly, since the allowlist blocked them; that rail is still only proven on
the container target.

---

## 4. `unit_name_for` is wrong for non-container quadlets

**Status: confirmed app bug, pre-existing, out of scope for the podman PR.**

`services/quadlet_naming.unit_name_for` maps every quadlet to `<base>.service`,
but podman only names *containers* that way. Verified against podman 5.8.4's
generator:

```
e2e-sleep.container -> e2e-sleep.service
e2e-test.pod        -> e2e-test-pod.service
e2e-test.volume     -> e2e-test-volume.service
e2e-test.network    -> e2e-test-network.service
```

`api/routes.py` `fetch_file` calls it for every type and passes the result to
the editor pane as both `unit_name` and the `status_url`. So for a `.volume`,
`.network` or `.pod`, the editor's status widget queries a unit that does not
exist. (Check the line number before citing it; it was `routes.py:573` on
2026-07-31.)

`services/stats_engine.py` already sidesteps this by only mapping `.container`,
with a comment explaining why, so the fix should not regress stats.

This is not theoretical. The same mistake in the podman suite's own teardown
stopped a unit that did not exist while the real one kept running, leaving a pod
and its infra container alive after a fully green run. See
`generated_unit_name` in `tests/podman/conftest.py` for the correct mapping.

**Filed as #286.** Decide there whether `unit_name_for` should take the quadlet
type, or whether callers should use a type-aware helper.

---

## 5. The new-quadlet modal's selects have no accessible name

**Status: confirmed accessibility gap, pre-existing.**

The three selects in the new-quadlet modal (`server_id`, `scope`, `type`) have
no `<label for>` and no `aria-label`. Two consequences:

* A screen reader announces three unlabelled comboboxes.
* `get_by_role("combobox", name="server_id")` cannot reach them, because that
  matches the *accessible* name, not the `name` attribute. An unscoped combobox
  lookup collides with the Shell and "Log time range" selects elsewhere on the
  page.

`tests/e2e/test_podman_e2e.py` therefore falls back to `select[name=...]`
attribute selectors, against the house preference for role-based locators set
out in [TESTING.md](TESTING.md#selecting-elements-in-e2e-tests). The comment
there explains why.

Adding labels fixes a real accessibility problem *and* lets that test use
`get_by_role` throughout, so the testing benefit is a side effect rather than
the motivation.

**Filed as #287.** Fits naturally alongside the Monitor accessibility work on
`issue-262-monitor-a11y` (#262).

Note for whoever picks it up: the labels are *present and visible*, they are
just not associated. The selects carry no `id` and the labels no `for`, so the
accessible name is empty. It is a smaller fix than "add labels" suggests.

---

## Filed elsewhere

Two more defects this work surfaced live in the tracker rather than here,
because neither is a testing follow-up:

* **#285**, `systemctl_action` issues a bare `systemctl --user` while
  `build_unit_state_command` beside it supplies `ROOTLESS_ENV_PREFIX`. Proven
  live in CI: `test_rootless_session_is_live` passed, because it builds the
  prefix itself, while all 17 tests going through `systemctl_action` errored.
* **#288**, the pre-existing `e2e` flake in
  `test_monitor_filter_narrows_glance_bar_and_shows_match_count`. Seen once
  during this branch's CI rounds, passed three times after on the same code, and
  this branch touches no frontend at all.

The glance bar bug the browser journeys exercise is **#281**, and
`tests/e2e/test_podman_e2e.py` carries a `xfail(strict=True)` test that flips to
a failure the day it is fixed.

---

## Smaller notes

* **The compose-based suites cannot run on a podman-only machine.** No compose
  provider is installed, so `integration` and `e2e` are unrunnable locally there.
  Pre-existing, and not introduced by the podman work, but it means a
  contributor on such a machine can only run three of the five suites. The
  podman suite is deliberately compose-free for this reason.
* **`UNMARKED_MARKEXPR` is duplicated by design.** It appears in
  `tests/conftest.py` and twice in `.github/workflows/tests.yml`, pinned
  together by `tests/test_unmarked_marker_sync.py`. If a cleaner mechanism turns
  up, the guard test can go with it.
