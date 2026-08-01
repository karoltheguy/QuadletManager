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

## 3. The loopback target has never been run

**Status: written and syntax-checked, never executed.**

`scripts/podman-e2e.sh setup-local` and `teardown-local` implement the second
target described in [TESTING.md](TESTING.md#the-two-targets), but neither has
been run once.

They were left alone on purpose: `setup-local` creates a real `quadlet-test`
system user, enables linger for it, and writes `/etc/sudoers.d/quadlet-test` on
the developer's own machine. That is not something to do unasked.

Two things make this worth doing rather than deleting:

* It is the only check that the narrow sudoers allowlist documented in
  `README.MD` and `docs/SETUP.MD` is actually sufficient to run the app. Nothing
  else verifies that today.
* It is the fast local loop, with no nesting and no image build.

**Next step:** run `sudo ./scripts/podman-e2e.sh setup-local`, then the suite
with `QM_PODMAN_HOST=localhost:22 QM_PODMAN_USER=quadlet-test`, then confirm
`teardown-local` leaves nothing behind. Until then, do not describe this target
as working. The safety rails in `tests/podman/conftest.py` matter most here,
because this target writes to the real `/etc/containers/systemd`.

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
