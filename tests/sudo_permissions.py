"""Read the two records of the app's root surface, each from where it lives.

* **The grant list** is `deploy/quadlet-manager.sudoers`, a real installable
  file rather than a code block. `tests/test_sudo_allowlist_sync.py` (unit)
  pins the one prose copy of it to this original.
* **The need list** is a table in `docs/SUDO_PERMISSIONS.md`, because it is
  documentation with no runtime form. `tests/podman/test_sudo_policy.py`
  (podman) asks a real host whether the grant list permits every entry in it.

Parsing the originals rather than restating them in a Python constant is the
point. A constant would be one more copy, and the reason any of this exists is
that the copies drifted.

The parsers are deliberately strict. An empty result from a silently renamed
file or heading would make every test pass while checking nothing, which is the
failure mode that let the gap in #289 survive twelve CI rounds.
"""

import os
import re
import shlex
from dataclasses import dataclass

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SUDOERS_PATH = os.path.join(REPO_ROOT, "deploy", "quadlet-manager.sudoers")
DOC_PATH = os.path.join(REPO_ROOT, "docs", "SUDO_PERMISSIONS.md")

# The placeholder the shipped sudoers file uses in place of a real account name.
AGENT_PLACEHOLDER = "%AGENT%"


@dataclass(frozen=True)
class RequiredCommand:
    """One command the app runs under sudo, as the policy test will probe it."""

    probe: str
    call_site: str
    notes: str

    @property
    def argv(self) -> list[str]:
        """The probe as sudo will see it, with shell quoting removed."""
        return shlex.split(self.probe)


def _document() -> str:
    with open(DOC_PATH, "r", encoding="utf-8") as handle:
        return handle.read()


def grant_rules(agent: str = AGENT_PLACEHOLDER) -> list[str]:
    """The shipped sudoers allowlist, one rule per line, in file order.

    Comments and blank lines are dropped, so the file can explain itself
    without the explanation becoming part of what is compared.

    `agent` substitutes for the account placeholder, exactly as the installers
    do: `quadlet-agent` in docs/SETUP.MD, `narrow` in Dockerfile.podman-host,
    `$LOOPBACK_USER` in scripts/podman-e2e.sh.
    """
    with open(SUDOERS_PATH, "r", encoding="utf-8") as handle:
        lines = handle.read().splitlines()

    rules = [
        line.strip()
        for line in lines
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not rules:
        raise AssertionError(
            f"{SUDOERS_PATH} yielded no rules. Every check that compares "
            "against it would then pass while comparing against nothing."
        )
    return [rule.replace(AGENT_PLACEHOLDER, agent) for rule in rules]


def required_commands() -> list[RequiredCommand]:
    """Every row of the need list table, in document order."""
    body = re.search(
        r"<!-- BEGIN NEED LIST -->(.*?)<!-- END NEED LIST -->",
        _document(),
        re.S,
    )
    if body is None:
        raise AssertionError(
            f"no BEGIN/END NEED LIST markers in {DOC_PATH}. Without them this "
            "returns nothing and the policy test asserts nothing."
        )

    commands = []
    for line in body.group(1).splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != 3:
            raise AssertionError(f"need list row has {len(cells)} cells, want 3: {line}")
        probe = cells[0]
        # Skip the header and its separator rather than special-casing position,
        # so a reordered table does not need a change here.
        if probe in ("Probe", "") or set(probe) <= set("-: "):
            continue
        commands.append(
            RequiredCommand(
                probe=_unbacktick(probe),
                call_site=cells[1],
                notes=cells[2],
            )
        )

    if not commands:
        raise AssertionError(f"parsed no need-list rows out of {DOC_PATH}")
    return commands


def _unbacktick(cell: str) -> str:
    """Strip the markdown code span a probe is written in."""
    match = re.fullmatch(r"`(.+)`", cell)
    if match is None:
        raise AssertionError(
            f"need-list probe {cell!r} is not wrapped in backticks. The probe "
            "cell is executed as a command line, so its exact text matters."
        )
    return match.group(1)
