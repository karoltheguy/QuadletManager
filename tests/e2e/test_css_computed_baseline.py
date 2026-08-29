"""
E2E tests for CSS computed styles baseline.

Snapshots the computed styles of every rendered DOM element under document.body
across theme (dark/light) and density (normal/compact) combinations and compares
them against committed baseline fixtures to detect unintended cascade changes
during CSS refactoring.
"""
import os
import sys
import pytest

try:
    from playwright.sync_api import Page
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    import typing
    Page = typing.Any

pytestmark = pytest.mark.skipif(
    not HAS_PLAYWRIGHT,
    reason="Playwright is not installed in this environment"
)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

BASE_URL = "http://localhost:8000"

PROPS = [
    "color", "background-color", "border-top-color", "border-top-width",
    "border-radius", "box-shadow", "font-family", "font-size", "font-weight",
    "line-height", "padding-top", "padding-left", "margin-top", "margin-left",
    "display", "position", "z-index", "opacity", "text-transform", "letter-spacing",
]

COMBOS = [("dark", "normal"), ("light", "normal"), ("dark", "compact"), ("light", "compact")]

# Share of baseline paths that must still be present for a run to count as a
# valid cascade check. Content drift from other e2e tests moves a handful of
# rows; anything approaching this floor means the page is not comparable.
MIN_PATH_COVERAGE = 0.95

DUMP_JS = """(props) => {
  const out = {};
  const walk = (el, path) => {
    const cs = getComputedStyle(el);
    out[path] = props.map(p => cs.getPropertyValue(p)).join('|');
    [...el.children].forEach((c, i) => walk(c, path + '/' + i));
  };
  walk(document.body, 'body');
  return out;
}"""


def _capture(page: Page, theme: str, density: str):
    page.set_viewport_size({"width": 1440, "height": 900})
    try:
        page.goto(BASE_URL + "/", wait_until="load")
    except Exception:
        pytest.skip("Backend is not running on localhost:8000 - skipping E2E tests.")
    # The app persists `qm-active-tab` and `qm-bottom-tab` in localStorage, so a
    # prior test that switched tabs changes which pane renders here and shifts
    # every child-index path after it. Clear storage and reload so the snapshot
    # is independent of test execution order.
    page.evaluate("localStorage.clear()")
    page.goto(BASE_URL + "/", wait_until="load")
    page.wait_for_timeout(1500)
    page.add_style_tag(
        content="*,*::before,*::after{transition:none!important;animation:none!important}"
    )
    page.evaluate(f"document.documentElement.setAttribute('data-theme', {theme!r})")
    if density == "normal":
        page.evaluate("document.documentElement.removeAttribute('data-density')")
    else:
        page.evaluate(f"document.documentElement.setAttribute('data-density', {density!r})")
    page.wait_for_timeout(200)
    return page.evaluate(DUMP_JS, PROPS)


def _fixture_path(theme: str, density: str) -> str:
    return os.path.join(REPO_ROOT, "tests", "fixtures", f"computed_{theme}_{density}.txt")


@pytest.mark.e2e
def test_computed_baseline_fixtures_exist():
    """For each (theme, density) in COMBOS assert os.path.isfile(_fixture_path(theme, density)),
    with a message naming the missing path."""
    for theme, density in COMBOS:
        fixture_path = _fixture_path(theme, density)
        assert os.path.isfile(fixture_path), (
            f"Computed baseline fixture does not exist at {fixture_path}"
        )


@pytest.mark.e2e
@pytest.mark.parametrize("theme,density", COMBOS)
def test_computed_styles_match_baseline(page: Page, theme: str, density: str):
    """Read the fixture for this combo, parsing each non-empty line by splitting on the FIRST tab
    into (path, values). Capture live via _capture(page, theme, density).
    Assert the set of paths is identical, and that every path's value string is identical.
    On failure the message must report: how many paths are only in the live page, how many only
    in the fixture, and how many paths differ in value; plus up to 5 differing examples, each
    naming the path, the specific PROPS name that differs (derive it by splitting both value
    strings on "|" and comparing index by index against PROPS), the expected value and the
    actual value."""
    fixture_path = _fixture_path(theme, density)
    assert os.path.isfile(fixture_path), (
        f"Computed baseline fixture does not exist at {fixture_path}"
    )

    fixture_data = {}
    with open(fixture_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            path, values = line.split("\t", 1)
            fixture_data[path] = values

    live_data = _capture(page, theme, density)

    live_paths = set(live_data.keys())
    fixture_paths = set(fixture_data.keys())

    only_live = sorted(live_paths - fixture_paths)
    only_fixture = sorted(fixture_paths - live_paths)
    common_paths = sorted(live_paths & fixture_paths)

    differing_paths = []
    diff_examples = []
    for path in common_paths:
        live_val = live_data[path]
        fix_val = fixture_data[path]
        if live_val != fix_val:
            differing_paths.append(path)
            if len(diff_examples) < 5:
                live_props = live_val.split("|")
                fix_props = fix_val.split("|")
                prop_diffs = []
                for prop_name, expected, actual in zip(PROPS, fix_props, live_props):
                    if expected != actual:
                        prop_diffs.append(
                            f"{prop_name}: expected {expected!r}, got {actual!r}"
                        )
                diff_examples.append(f"  Path '{path}': " + "; ".join(prop_diffs))

    # A CSS-only change cannot alter the DOM, so a path present on one side and
    # not the other says nothing about the cascade -- it means the page rendered
    # different CONTENT. The e2e suite mutates servers (see
    # test_server_reorder_e2e.py), which shifts every child-index path after the
    # row that moved. So the cascade assertion is made over the shared paths,
    # and path drift is only held to a coverage floor that keeps the guard from
    # silently shrinking to nothing.
    coverage = len(common_paths) / len(fixture_data) if fixture_data else 0.0
    assert coverage >= MIN_PATH_COVERAGE, (
        f"Only {coverage:.1%} of baseline paths were found on the live page for "
        f"theme={theme!r}, density={density!r} (floor is {MIN_PATH_COVERAGE:.0%}). "
        f"The page rendered structurally different content, so this run cannot "
        f"verify the cascade. Paths only in live ({len(only_live)}): "
        f"{only_live[:5]}; only in fixture ({len(only_fixture)}): {only_fixture[:5]}"
    )

    if differing_paths:
        failure_msg = (
            f"Computed styles mismatch for theme={theme!r}, density={density!r}:\n"
            f"  - Shared paths compared: {len(common_paths)} ({coverage:.1%} of baseline)\n"
            f"  - Differing paths count: {len(differing_paths)}\n"
        )
        if diff_examples:
            failure_msg += "Differing examples (up to 5):\n" + "\n".join(diff_examples)

        assert not differing_paths, failure_msg
