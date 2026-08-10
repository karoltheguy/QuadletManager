"""The app version, and the rules CI uses to compute it.

The git tag is the single source of truth. `get_version()` is the runtime read;
`ci_version()` is what `container-build.yml` bakes into an image via the
`APP_VERSION` build arg. Both live here so there is exactly one place the
version rules are written down.

Stdlib only, deliberately: the container-build job checks the repo out but
installs no Python dependencies, and invokes this module as
`python3 -m core.version`.
"""

import os
import re
import subprocess
import sys
from functools import lru_cache

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Matches the leading `X.Y.Z` of a tag, ignoring any `-rc.1` prerelease or
# `+meta` build-metadata segment that follows it.
_CORE_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)")

DEV_IDENTIFIER = "dev"


class TagLookupError(RuntimeError):
    """Raised when a dev build cannot find a tag to derive its version from.

    Only CI raises this. A tagless checkout used to fall back to `v0.0.0`,
    which silently versioned every `main` image `0.1.0-dev.N` -- a plausible
    string that marches backwards from the `0.4.0-dev.N` the previous build
    reported. `container-build.yml` sets `fetch-depth: 0` precisely to prevent
    it, and this turns a regression there into a failed build rather than a
    quietly mis-versioned image.
    """


@lru_cache(maxsize=1)
def _describe_version():
    """Runs `git describe --tags --dirty` and returns the tag with any leading
    'v' stripped, or None if git is unavailable, the command fails, or times out."""
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--dirty"],
            cwd=_BASE_DIR,
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return None

    return result.stdout.strip().removeprefix("v")


def get_version() -> str:
    """Returns the app version: the APP_VERSION env var if set and non-empty
    (this is how container builds ship a version baked in at build time);
    otherwise derives it from `git describe --tags --dirty` for local dev
    runs, appending '+dev', or falls back to '0.0.0+dev' if git is
    unavailable."""
    env_version = os.getenv("APP_VERSION")
    if env_version:
        return env_version

    described = _describe_version()
    if described is None:
        return "0.0.0+dev"
    return f"{described}+dev"


def latest_tag():
    """Returns the most recent tag reachable from HEAD, or None when the checkout
    has no tags (a depth-1 checkout fetches none) or git is unavailable.

    None rather than a `v0.0.0` stand-in: a real `v0.0.0` tag and a failed
    lookup must not produce the same version, or the failure is unreportable.
    """
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0"],
            cwd=_BASE_DIR,
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return None

    return result.stdout.strip() or None


def next_dev_version(base_tag: str, run_number: str) -> str:
    """Returns the version for a development build sitting ahead of `base_tag`,
    e.g. ('v0.3.0', '514') -> '0.4.0-dev.514'.

    A semver *prerelease* rather than build metadata, because the spec ignores
    build metadata for precedence: `0.3.0+build.514` compared equal to the
    `0.3.0` release the image was actually ahead of, and read identically to a
    release in the UI. `0.4.0-dev.514` sorts after `0.3.0` and before `0.4.0`,
    and says what it is.

    The minor is always bumped, and always from the *core* `X.Y.Z` of the base,
    so a prerelease base overshoots: `v0.4.0-rc.1` yields `0.5.0-dev.N` rather
    than the `0.4.0-dev.N` that would be strictly correct. That is accepted.
    Bumping unconditionally is what guarantees the useful property -- a dev
    version always sorts after every tag that already exists -- and getting the
    rc case exactly right needs a prerelease identifier that sorts after `rc`,
    which no fixed word provides.

    An unparseable base falls back to a `0.0.0` core, yielding `0.1.0-dev.N`.
    A *missing* base is a different case and never reaches here: ci_version()
    raises TagLookupError instead.
    """
    match = _CORE_VERSION.match(base_tag)
    if match is None:
        major, minor = 0, 0
    else:
        major, minor = int(match.group(1)), int(match.group(2)) + 1

    return f"{major}.{minor}.0-{DEV_IDENTIFIER}.{run_number}"


def ci_version(ref_type: str, ref_name: str, run_number: str, tag_reader=None) -> str:
    """Returns the version CI bakes into an image.

    A tag build is the release it says it is, so the run number goes in build
    metadata: `v0.3.0` on run 520 becomes `0.3.0+build.520`. Semver ignores
    metadata for precedence, which is exactly right here -- the image compares
    equal to `0.3.0`, while still naming the run that produced it.

    Any other build is ahead of the most recent tag and gets a prerelease of the
    next release instead. See next_dev_version(). Raises TagLookupError if no
    tag can be read, rather than inventing a base and mis-versioning the image.

    A tag build never consults git, so it still succeeds on a tagless checkout:
    the ref itself carries the version.
    """
    if ref_type == "tag":
        return f"{ref_name.removeprefix('v')}+build.{run_number}"

    # Resolved here rather than as a default argument, which would bind the
    # module-level function once at import and ignore any later substitution.
    base_tag = (tag_reader or latest_tag)()
    if base_tag is None:
        raise TagLookupError(
            "no git tag reachable from HEAD.\n"
            "  container-build.yml needs `fetch-depth: 0`;\n"
            "  a depth-1 checkout fetches no tags."
        )

    return next_dev_version(base_tag, run_number)


def main() -> int:
    """Prints the CI version for the current GitHub Actions environment.

    Invoked as `python3 -m core.version` by container-build.yml. Returns 1 on a
    failed tag lookup so the workflow step fails and no image is published.
    """
    try:
        version = ci_version(
            os.environ.get("GITHUB_REF_TYPE", ""),
            os.environ.get("GITHUB_REF_NAME", ""),
            os.environ.get("GITHUB_RUN_NUMBER", "0"),
        )
    except TagLookupError as exc:
        print(f"core.version: {exc}", file=sys.stderr)
        return 1

    print(version)
    return 0


if __name__ == "__main__":
    sys.exit(main())
