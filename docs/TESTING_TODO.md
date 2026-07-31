# Testing follow-ups

Open items left by the `podman` suite work. Each was found by running the suite
against a real host, and each was deliberately left undone rather than
overlooked, with the reason recorded.

Order is roughly by how much it matters, not by effort.

---

## 1. The podman CI job has never actually run

**Status: unknown, not merely unverified.**

The workflow entry, compose profile and readiness gate are written and their
YAML parses, but no push has exercised them. Everything about the podman suite
that is proven is proven *locally*, on one machine, against a container built by
`scripts/podman-e2e.sh` rather than by compose.

Plausible differences on a GitHub runner:

* the compose build path differs from the local `podman build`,
* the runner's Docker daemon is rootful by default, which is what the image
  needs, but its storage driver and cgroup setup are not identical,
* the readiness gate's staged waits have never had their timeouts tested
  against a cold runner.

**Next step:** push the branch and watch the `GitHub / podman` job. Treat the
first run as an experiment, not a formality.

---

## 2. The loopback target has never been run

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

## 3. `unit_name_for` is wrong for non-container quadlets

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

**Next step:** file an issue. Decide whether `unit_name_for` should take the
quadlet type, or whether callers should use a type-aware helper.

---

## 4. The new-quadlet modal's selects have no accessible name

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

**Next step:** file an issue. Fits naturally alongside the Monitor
accessibility work on `issue-262-monitor-a11y`.

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
