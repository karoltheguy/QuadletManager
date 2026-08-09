# Releasing

QuadletManager follows [Semantic Versioning](https://semver.org/). While the
project is on `0.x`, **breaking changes bump the minor** (`0.1.0` -> `0.2.0`);
the major stays at `0` until the API and on-disk formats are stable.

The single source of truth for the version is the git tag `vX.Y.Z`, read via
`git describe` by `core/version.py` and surfaced in the startup log and the
`/api/...` app-info payload.

## Day-to-day work

Nothing about ordinary development changes:

1. Branch off `main`.
2. Open a PR. `tests.yml` runs, and `container-build.yml` builds the image
   without pushing it (`push:` is gated on the event not being a PR).
3. Merge to `main`. That publishes `ghcr.io/karoltheguy/quadletmanager:main`
   and `:sha-<full-sha>`, with an app version derived from the most recent
   tag as `<base>+build.<run>`.

`main` is a development build. It is **not** `latest`.

## Cutting a release

1. Tag the commit on `main` you want to release and push the tag:

   ```bash
   git checkout main && git pull
   git tag -a v0.2.0 -m "v0.2.0"
   git push origin v0.2.0
   ```

There is no bump PR: the tag itself is the version.

That tag push runs `release.yml`, which owns the whole release as one linear
pipeline:

```
test ──> image ──> release
```

- **`test`** calls `tests.yml` as a reusable workflow. The full suite must be
  green before anything outward-facing happens.
- **`image`** calls `container-build.yml`, publishing `:0.2.0`, `:0.2`,
  `:latest`, and `:sha-<full-sha>`, with the app version baked in as a clean
  `0.2.0`.
- **`release`** creates the GitHub Release with auto-generated notes. GitHub
  attaches the source `.tar.gz` and `.zip` automatically — that is the
  download for anyone running from source, so no artifact needs to be built
  or uploaded.

Because each stage gates the next, a red suite means no image is pushed and no
Release is published. `container-build.yml` deliberately does **not** trigger
on tags itself; if it did, `:latest` could move before the tests finished.

A called workflow evaluates against the *caller's* context, so inside `test`
and `image` the values of `github.ref`, `github.ref_type`, and
`github.event_name` are the same ones a direct tag push would produce. That is
what keeps the semver tagging, the `:latest` gate, and the bare-version
`APP_VERSION` working unchanged after the move.

### Prereleases

Tag with a prerelease segment (`v0.2.0-rc.1`). `release.yml` passes
`--prerelease`, so GitHub does not promote it to "Latest release". Note that
the `image` stage still moves the `:latest` container tag for any `v*.*.*`
tag — if that matters for a given prerelease, publish it from a branch rather
than a tag.

### If a tag was pushed wrong

Delete it locally and remotely, then tag again:

```bash
git push origin :refs/tags/v0.2.0
git tag -d v0.2.0
```

Delete the GitHub Release too if `release.yml` already created one, otherwise
re-tagging will fail on the existing release.
