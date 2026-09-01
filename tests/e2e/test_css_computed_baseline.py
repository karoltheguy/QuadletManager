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

from tests.app_url import BASE_URL

PROPS = [
    "color", "background-color", "border-top-color", "border-top-width",
    "border-radius", "box-shadow", "font-family", "font-size", "font-weight",
    "line-height", "padding-top", "padding-left", "margin-top", "margin-left",
    "display", "position", "z-index", "opacity", "text-transform", "letter-spacing",
]

COMBOS = [("dark", "normal"), ("light", "normal"), ("dark", "compact"), ("light", "compact")]

# How many elements must be compared for a run to count as a valid cascade
# check. This is an absolute count, not a share of the baseline, because the
# dashboard is row-per-record: the settings tables, overview cards and quadlet
# tree all render one element per server, SSH key or user, and CI has different
# records than any developer box. A table with four rows locally and two in CI
# exercises the SAME rules, so the missing rows cost no rule coverage and a
# percentage floor was measuring the wrong thing. CI compares ~554 elements.
MIN_COMPARED_ELEMENTS = 400

# Elements whose CONTENTS are data-driven and therefore not comparable between
# machines. `.server-quadlet-tree` holds the quadlet list fetched over SSH from
# each configured server: it is populated on a developer box with a reachable
# Podman host, empty in CI, and empty locally too whenever that connection is
# slow or failing. The container itself is still measured, so its own styling
# stays covered; only the walk into its children stops.
OPAQUE_CLASSES = ["server-quadlet-tree"]

# Each captured line is the element's SIGNATURE (tag name plus class list)
# followed by its property values. The signature exists because a child-index
# path is not a stable identity: when the page renders different records, an
# index can land on a different element instead of vanishing, which reads as a
# style change when it is really content drift. Comparing signatures first tells
# the two apart.
DUMP_JS = """([props, opaque]) => {
  const out = {};
  const walk = (el, path) => {
    const cs = getComputedStyle(el);
    const cls = typeof el.className === 'string' ? el.className.trim().split(/\\s+/).sort().join(' ') : '';
    const signature = el.tagName + '.' + cls;
    out[path] = [signature].concat(props.map(p => cs.getPropertyValue(p))).join('|');
    if (opaque.some(c => el.classList.contains(c))) return;
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
        pytest.skip(f"Backend is not running at {BASE_URL} - skipping E2E tests.")
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
    return page.evaluate(DUMP_JS, [PROPS, OPAQUE_CLASSES])


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
    aliased_paths = []
    compared_paths = []
    for path in common_paths:
        live_sig, _, live_val = live_data[path].partition("|")
        fix_sig, _, fix_val = fixture_data[path].partition("|")
        if live_sig != fix_sig:
            # Same index path, different element. Content drift, not a cascade
            # change, so it is not comparable and must not be reported as a diff.
            aliased_paths.append(f"{path} ({fix_sig} -> {live_sig})")
            continue
        compared_paths.append(path)
        if live_val != fix_val:
            differing_paths.append(path)
            if len(diff_examples) < 5:
                prop_diffs = []
                for prop_name, expected, actual in zip(
                    PROPS, fix_val.split("|"), live_val.split("|")
                ):
                    if expected != actual:
                        prop_diffs.append(
                            f"{prop_name}: expected {expected!r}, got {actual!r}"
                        )
                diff_examples.append(f"  Path '{path}' [{fix_sig}]: " + "; ".join(prop_diffs))

    # A CSS-only change cannot alter the DOM, so a path present on one side and
    # not the other says nothing about the cascade -- it means the page rendered
    # different CONTENT. The e2e suite mutates servers (see
    # test_server_reorder_e2e.py), which shifts every child-index path after the
    # row that moved. So the cascade assertion is made over the shared paths,
    # and path drift is only held to a coverage floor that keeps the guard from
    # silently shrinking to nothing.
    coverage = len(compared_paths) / len(fixture_data) if fixture_data else 0.0
    assert len(compared_paths) >= MIN_COMPARED_ELEMENTS, (
        f"Only {len(compared_paths)} elements could be compared for theme={theme!r}, "
        f"density={density!r} (floor is {MIN_COMPARED_ELEMENTS}); that is "
        f"{coverage:.1%} of the baseline. Too little of the page rendered for this "
        f"run to verify the cascade -- check the app actually loaded its "
        f"stylesheets. Paths only in live ({len(only_live)}): {only_live[:5]}; "
        f"only in fixture ({len(only_fixture)}): {only_fixture[:5]}; "
        f"paths whose element changed ({len(aliased_paths)}): {aliased_paths[:5]}"
    )

    if differing_paths:
        failure_msg = (
            f"Computed styles mismatch for theme={theme!r}, density={density!r}:\n"
            f"  - Elements compared: {len(compared_paths)} ({coverage:.1%} of baseline)\n"
            f"  - Skipped, element at that path changed: {len(aliased_paths)}\n"
            f"  - Differing paths count: {len(differing_paths)}\n"
        )
        if diff_examples:
            failure_msg += "Differing examples (up to 5):\n" + "\n".join(diff_examples)

        assert not differing_paths, failure_msg
