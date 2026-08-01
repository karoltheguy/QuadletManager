"""Read docs/SUDO_PERMISSIONS.md, the one record of the app's root surface.

Two tests consume this module and they want different halves of that file:

* `tests/test_sudo_allowlist_sync.py` (unit) takes the grant list and pins it to
  the three published copies.
* `tests/podman/test_sudo_policy.py` (podman) takes the need list and asks a
  real host whether the grant list permits each entry.

Parsing a document rather than duplicating it into a Python constant is the
whole point. A constant would be a fourth copy, and the reason this exists is
that the existing three drifted.

The parsers are deliberately strict. An empty result from a silently changed
heading would make both tests pass while checking nothing, which is the failure
mode that let the gap in #289 survive twelve CI rounds.
"""

import os
import re
import shlex
from dataclasses import dataclass

DOC_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "docs",
    "SUDO_PERMISSIONS.md",
)

# The placeholder the grant list uses in place of a real account name.
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
    """The published sudoers allowlist, one rule per line, in document order.

    `agent` substitutes for the account placeholder, so a caller comparing
    against README.MD asks for `quadlet-agent` and one comparing against
    scripts/podman-e2e.sh asks for `$LOOPBACK_USER`.
    """
    blocks = re.findall(r"^```sudoers\n(.*?)^```", _document(), re.M | re.S)
    if len(blocks) != 1:
        raise AssertionError(
            f"expected exactly one ```sudoers block in {DOC_PATH}, found "
            f"{len(blocks)}. The grant list is parsed by that fence alone, so "
            "a second one makes it ambiguous and none makes it empty."
        )
    rules = [line.strip() for line in blocks[0].splitlines() if line.strip()]
    if not rules:
        raise AssertionError(f"the ```sudoers block in {DOC_PATH} is empty")
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
