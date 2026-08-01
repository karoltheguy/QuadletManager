"""The sudoers allowlist is published in four places, so pin them together.

* `README.MD` section 2, for someone setting up a server.
* `docs/SETUP.MD` section 3, same rules, written out again.
* `scripts/podman-e2e.sh`, which installs them for the loopback test target.
* `Dockerfile.podman-host`, which installs them for the `narrow` account that
  tests/podman/test_sudo_policy.py probes.

`docs/SUDO_PERMISSIONS.md` is the source those three copy. Nothing enforced that
before this test: the copies could drift, and drift is not a cosmetic problem
here. The loopback target exists to prove the *published* policy is enough to
run the app, and it can only prove that about the rules it actually installs. A
script that has quietly gained a rule the README lacks reports a green run for a
configuration no user has.

Modelled on tests/test_unmarked_marker_sync.py, which does the same job for
UNMARKED_MARKEXPR, and marked `unit` for the same reason: this needs no podman
host, so it catches drift in the fast job rather than in the slow one.
"""

import os
import re

import pytest

from tests.sudo_permissions import grant_rules

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Each copy names the account differently. The rules are otherwise identical,
# so the account name is the only substitution needed to compare them.
DOCS_AGENT = "quadlet-agent"
SCRIPT_AGENT = "$LOOPBACK_USER"
CONTAINER_AGENT = "narrow"


def _read(relative_path):
    with open(os.path.join(BASE_DIR, relative_path), "r", encoding="utf-8") as handle:
        return handle.read()


def _rules_in(relative_path, agent):
    """Every sudoers rule for `agent` in a file, in the order it lists them.

    Matches on the rule shape rather than on a fenced block or line numbers, so
    prose can move the rules around without breaking this.

    The leading and trailing quotes are for Dockerfile.podman-host, which lists
    the same rules as single-quoted arguments to `printf '%s\\n'`. Matching them
    in place beats parsing the shell: the rules are still one per line and still
    literal, which is all this needs.
    """
    pattern = re.compile(
        r"^[ \t'\"]*" + re.escape(agent) + r"\s+ALL=\(ALL\)\s+NOPASSWD:[^'\"\n]*",
        re.M,
    )
    return [match.strip(" \t'\"") for match in pattern.findall(_read(relative_path))]


COPIES = [
    ("README.MD", DOCS_AGENT),
    ("docs/SETUP.MD", DOCS_AGENT),
    ("scripts/podman-e2e.sh", SCRIPT_AGENT),
    ("Dockerfile.podman-host", CONTAINER_AGENT),
]


@pytest.mark.unit
def test_source_of_truth_is_not_empty():
    """If the parser silently returned nothing, every test below would pass."""
    rules = grant_rules(DOCS_AGENT)
    assert len(rules) >= 8, (
        f"docs/SUDO_PERMISSIONS.md yielded only {len(rules)} grant rules. The "
        "published allowlist has had eight since it was written, so a shorter "
        "list means the parser stopped finding them, not that rules were removed."
    )
    assert all(rule.startswith(DOCS_AGENT) for rule in rules)


@pytest.mark.unit
@pytest.mark.parametrize("relative_path,agent", COPIES)
def test_copy_matches_source_of_truth(relative_path, agent):
    expected = grant_rules(agent)
    actual = _rules_in(relative_path, agent)
    assert actual == expected, (
        f"the sudoers allowlist in {relative_path} has drifted from "
        "docs/SUDO_PERMISSIONS.md.\n"
        f"  in {relative_path}: {actual}\n"
        f"  in the source doc:  {expected}\n"
        "Edit docs/SUDO_PERMISSIONS.md, then bring every copy across to match."
    )


@pytest.mark.unit
def test_every_path_rule_is_scoped_to_the_quadlet_directory():
    """A rule that lets the agent write anywhere is a root grant, not an allowlist.

    `tee /etc/containers/systemd/*` plus `daemon-reload` plus `systemctl start *`
    is already a unit file and a way to run it, which is as far as this policy
    should go. A `tee /*` would be the same grant with none of the containment,
    and the difference is one character.
    """
    for rule in grant_rules(DOCS_AGENT):
        for token in rule.split():
            if token.startswith("/") and "*" in token:
                assert token.startswith("/etc/containers/systemd/"), (
                    f"{rule!r} contains a wildcard path outside the quadlet "
                    f"directory: {token!r}"
                )
