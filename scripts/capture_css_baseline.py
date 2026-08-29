"""Capture CSS cascade baseline fixture from stylesheets.

The fixture is a snapshot guard for the static/style.css sheet split tracked in
issue #174, and it must be regenerated deliberately whenever CSS legitimately
changes.
"""
import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from api.routes import STYLESHEETS
from tests.css_source import rule_blocks, strip_comments


def capture_css_baseline() -> None:
    """Read stylesheets, extract normalized rule blocks, and write to baseline fixture."""
    live_contents = []
    for sheet in STYLESHEETS:
        sheet_path = os.path.join(REPO_ROOT, "static", sheet)
        with open(sheet_path, "r", encoding="utf-8") as f:
            live_contents.append(f.read())

    combined_css = "\n".join(live_contents)
    blocks = rule_blocks(strip_comments(combined_css))
    sorted_blocks = sorted(blocks)

    fixtures_dir = os.path.join(REPO_ROOT, "tests", "fixtures")
    os.makedirs(fixtures_dir, exist_ok=True)
    baseline_path = os.path.join(fixtures_dir, "css_cascade_baseline.txt")

    with open(baseline_path, "w", encoding="utf-8") as f:
        for block in sorted_blocks:
            f.write(f"{block}\n")

    print(f"Wrote {len(sorted_blocks)} rule blocks to {baseline_path}")


if __name__ == "__main__":
    capture_css_baseline()
