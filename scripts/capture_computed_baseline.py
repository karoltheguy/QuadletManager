"""Capture CSS computed style baseline fixtures across themes and densities.

Regenerates the computed-style cascade guard for the static/style.css sheet split
tracked in issue #174.

This script REQUIRES a backend running on localhost:8000 and Playwright browsers
installed. The fixtures must be regenerated deliberately whenever CSS
legitimately changes.
"""
import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from playwright.sync_api import sync_playwright

from tests.e2e.test_css_computed_baseline import COMBOS, _capture, _fixture_path


def capture_computed_baseline() -> None:
    """Capture computed styles for each combo and write sorted fixture files."""
    fixtures_dir = os.path.join(REPO_ROOT, "tests", "fixtures")
    os.makedirs(fixtures_dir, exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        for theme, density in COMBOS:
            data = _capture(page, theme, density)
            fixture_path = _fixture_path(theme, density)
            sorted_paths = sorted(data.keys())
            with open(fixture_path, "w", encoding="utf-8") as f:
                f.writelines(f"{path}\t{data[path]}\n" for path in sorted_paths)
            print(f"Wrote {len(sorted_paths)} elements to {fixture_path}")
        browser.close()


if __name__ == "__main__":
    capture_computed_baseline()
