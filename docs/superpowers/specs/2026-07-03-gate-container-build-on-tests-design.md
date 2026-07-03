# Gate main-branch container publish on all test suites passing

## Problem

`container-build.yml` currently builds and pushes the container image on every
push to `main`, independent of `tests.yml`'s result. The two workflows are
separate files and run in parallel, so a broken `main` commit can still get a
`latest` image published to `ghcr.io`.

## Scope

Only the **main-branch push** path (the one that publishes `latest`) needs to
be gated. The other two `container-build.yml` triggers are unaffected:

- **Tag pushes** (`v*.*.*`): left ungated. A release tag is cut deliberately,
  after `main` is already known-good.
- **Pull requests**: left ungated. PR builds already never push
  (`push: ${{ github.event_name != 'pull_request' }}`) — they're a build-only
  sanity check, not a publish.

`tests.yml` stays a single file (not split or merged with
`container-build.yml`) per explicit preference — it's already handling two
runner backends (GitHub/Forgejo) via a `github.server_url` condition, and
adding a third concern (publish gating) to it was rejected as unnecessary
complexity.

## Design

### 1. Trigger via `workflow_run` instead of `push: branches: [main]`

`container-build.yml` adds a `workflow_run` trigger watching the `Tests`
workflow, replacing the `push: branches: [main]` entry (tag pushes stay on
the `push` trigger):

```yaml
on:
  push:
    tags: [ "v*.*.*" ]
  pull_request:
    branches: [ "main" ]
  workflow_run:
    workflows: ["Tests"]
    types: [completed]
  workflow_dispatch:
```

The `build-and-push` job gate becomes:

```yaml
if: >
  github.server_url == 'https://github.com' &&
  (
    github.event_name != 'workflow_run' ||
    (github.event.workflow_run.conclusion == 'success' &&
     github.event.workflow_run.head_branch == 'main' &&
     github.event.workflow_run.event == 'push')
  )
```

`head_branch == 'main' && event == 'push'` is required because `Tests` also
runs on PR branches — without this filter, a PR's green test run would
spuriously trigger a main-branch container publish.

`workflow_run`'s `conclusion` reflects the entire `Tests` run, which is an
aggregate across the `test-github` matrix (`fail-fast: false`, so any failing
suite — unit/unmarked/integration/e2e — flips the aggregate to `failure`).
This is what gives us "all test suites green" as a single boolean without
extra bookkeeping.

### 2. Pin the exact tested commit (checkout + image tag)

`workflow_run` always evaluates the workflow file from the default branch,
and its `github.sha`/`github.ref` context defaults to the tip of `main` —
not necessarily the exact commit `Tests` validated, if another push landed
in between. Two places need the exact SHA:

**Checkout** — resolve the SHA once, use it explicitly:

```yaml
- name: Resolve commit SHA to build
  id: resolve
  run: |
    if [ "${{ github.event_name }}" = "workflow_run" ]; then
      echo "sha=${{ github.event.workflow_run.head_sha }}" >> "$GITHUB_OUTPUT"
    else
      echo "sha=${{ github.sha }}" >> "$GITHUB_OUTPUT"
    fi

- name: Checkout repository
  uses: actions/checkout@v4
  with:
    ref: ${{ steps.resolve.outputs.sha }}
```

**Image tag** — `docker/metadata-action` has no override for its automatic
`type=sha` tag (it reads `github.sha` internally, which has the same
staleness risk). Drop `type=sha,format=long` and replace it with an explicit
raw tag using the resolved SHA:

```yaml
tags: |
  type=ref,event=branch
  type=ref,event=pr
  type=semver,pattern={{version}}
  type=semver,pattern={{major}}.{{minor}}
  type=raw,value=${{ steps.resolve.outputs.sha }}
  type=raw,value=latest,enable={{is_default_branch}}
```

Known side effect: `type=ref,event=branch` requires
`github.event_name == 'push'` internally, so it silently produces no tag on
`workflow_run`-triggered builds. This is acceptable — `latest` (which checks
`is_default_branch` via `github.ref`, unaffected by event type) and the
explicit SHA tag already cover the practical need for main-branch images.

### 3. Decouple Codacy coverage upload from the publish gate

`tests.yml`'s `upload-coverage` job runs after `test-github` and uploads
coverage to Codacy. If it fails for a reason unrelated to test correctness
(Codacy outage, token issue), the whole `Tests` workflow run's conclusion
becomes `failure`, which would block the container publish even though every
test suite passed.

Fix: add `continue-on-error: true` to the `upload-coverage` job in
`tests.yml`. The job still runs and still shows failed/red in the Actions UI
and PR checks (so a real Codacy problem stays visible) — it just no longer
flips the overall workflow run's conclusion, which is the only thing
`container-build.yml`'s `workflow_run.conclusion` check reads.

`test-github` (and its matrix legs) do **not** get `continue-on-error` — an
actual test suite failure must still block the publish.

## Files touched

- `.github/workflows/container-build.yml` — trigger change, gate condition,
  SHA resolution/checkout, metadata tag list.
- `.github/workflows/tests.yml` — `continue-on-error: true` added to the
  `upload-coverage` job. No other changes.

## Out of scope

- Gating tag-push or PR builds on test results.
- Merging `tests.yml` and `container-build.yml` into one workflow file.
- Changing what `test-forgejo` or `upload-coverage` actually do, beyond the
  `continue-on-error` flag.

## Testing

Workflow-file changes can't be unit-tested; verification is by inspection
(review the diff against this design) plus observing real runs after merge:
a main push with all suites green should trigger a build/push, a main push
with a failing suite should not, and a main push where only Codacy upload
fails should still trigger a build/push.
