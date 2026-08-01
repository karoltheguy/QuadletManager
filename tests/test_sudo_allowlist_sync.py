"""Keep the sudoers allowlist to one original and one readable copy.

`deploy/quadlet-manager.sudoers` is the original: a real installable file with
`%AGENT%` where the account name goes. Everything that installs the allowlist
substitutes into it rather than restating it, so there is nothing to drift.

`docs/SETUP.MD` reproduces the rules anyway, because someone configuring a
server should be able to read them without opening a second file. That copy is
the one thing here that can drift, and these tests are what stop it.

The rules used to be written out in four places: README.MD, docs/SETUP.MD,
scripts/podman-e2e.sh and Dockerfile.podman-host. Three of those were
installers that never needed the text, only a file to substitute into, and the
fourth duplicated docs/SETUP.MD for the same reader. Drift there is not
cosmetic: the loopback target exists to prove the *published* policy is enough
to run the app, and it can only prove that about the rules it actually
installs. A script that had quietly gained a rule the docs lacked would report
a green run for a configuration no user has.

Marked `unit`, so this runs in the fast job with no podman host anywhere near
it. Modelled on tests/test_unmarked_marker_sync.py, which does the same job for
UNMARKED_MARKEXPR.
"""

import os
import re

import pytest

from tests.sudo_permissions import AGENT_PLACEHOLDER, SUDOERS_PATH, grant_rules

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The account name docs/SETUP.MD substitutes when it shows the rules.
DOCS_AGENT = "quadlet-agent"

# Files that install the allowlist. Each must read the original rather than
# carry its own copy of the rules.
INSTALLERS = ["scripts/podman-e2e.sh", "Dockerfile.podman-host"]

# Any line granting NOPASSWD sudo to anybody, whatever the account is called.
# The optional quotes are for Dockerfile-style `printf '%s\n' 'rule' \` lines,
# so that re-inlining the rules there is still detected.
ANY_RULE = re.compile(
    r"^[ \t'\"]*(\S+)\s+ALL=\(ALL\)\s+NOPASSWD:\s*(\S.*?)[ '\"\\]*$", re.M
)


def _read(relative_path):
    with open(os.path.join(BASE_DIR, relative_path), "r", encoding="utf-8") as handle:
        return handle.read()


def _rules_written_out_in(relative_path):
    """Every fully written sudoers rule in a file, normalised for comparison."""
    return [
        f"{agent} ALL=(ALL) NOPASSWD: {command}"
        for agent, command in ANY_RULE.findall(_read(relative_path))
    ]


@pytest.mark.unit
def test_the_original_is_not_empty():
    """If the parser silently returned nothing, every test below would pass."""
    rules = grant_rules(DOCS_AGENT)
    assert len(rules) >= 8, (
        f"{SUDOERS_PATH} yielded only {len(rules)} rules. The published "
        "allowlist has had eight since it was written, so a shorter list means "
        "the parser stopped finding them, not that rules were removed."
    )
    assert all(rule.startswith(DOCS_AGENT) for rule in rules)


@pytest.mark.unit
def test_setup_doc_matches_the_original():
    expected = grant_rules(DOCS_AGENT)
    actual = _rules_written_out_in("docs/SETUP.MD")
    assert actual == expected, (
        "the sudoers allowlist quoted in docs/SETUP.MD has drifted from "
        "deploy/quadlet-manager.sudoers.\n"
        f"  in docs/SETUP.MD: {actual}\n"
        f"  in the original:  {expected}\n"
        "Edit deploy/quadlet-manager.sudoers, then bring the doc across."
    )


@pytest.mark.unit
@pytest.mark.parametrize("relative_path", INSTALLERS)
def test_installers_substitute_rather_than_duplicate(relative_path):
    """An installer that embeds the rules has recreated the original problem.

    This is what keeps the collapse from quietly undoing itself. Pasting eight
    lines into a Dockerfile is easier than wiring up a COPY, and the result
    looks fine right up until the two disagree.
    """
    text = _read(relative_path)

    # A verbatim inline of the original would still carry %AGENT%, which is not
    # duplication of the resolved rules; anything else is.
    embedded = [
        rule
        for rule in _rules_written_out_in(relative_path)
        if AGENT_PLACEHOLDER not in rule
    ]
    assert not embedded, (
        f"{relative_path} writes sudoers rules out in full instead of "
        "substituting into deploy/quadlet-manager.sudoers:\n"
        + "\n".join(f"  {rule}" for rule in embedded)
        + "\nThat is the duplication issue #289 came from. Read the file and "
        "sed the account name in, as this installer used to."
    )

    assert "quadlet-manager.sudoers" in text, (
        f"{relative_path} installs a sudoers policy but never mentions "
        "deploy/quadlet-manager.sudoers, so it is no longer installing the "
        "published allowlist."
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
