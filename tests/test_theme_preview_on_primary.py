"""
Tests for the theme customization *preview* path emitting a derived
--brand-on-primary foreground token (Issue #233).

`api/routes.py` already derives a WCAG AA (>= 4.5:1) compliant
--brand-on-primary via `_on_primary_for()` for the SAVED theme (see Issue
#232 / tests/test_theme_on_primary_contrast.py). The live client-side
PREVIEW built by `applyThemePreview(form)` in `static/main.js` has no such
logic: it only iterates the eight `<input type="color" name="...">`
pickers on the form and emits their raw values as CSS custom properties, so
no `--brand-on-primary` rule is ever written into the `#qm-theme-preview`
`<style>` block. This means a user previewing a hostile brand_primary color
sees a settings primary button whose foreground text can fail WCAG AA,
even though the same color would get a correctly-derived foreground once
saved.

This test file asserts:
1. A JS mirror of `_on_primary_for` (named `onPrimaryFor`, plus helpers
   `linearize`, `relativeLuminance`, `contrastRatio`) exists in
   `static/main.js` and produces results identical to the Python
   `_on_primary_for()` for a fixed color corpus.
2. `applyThemePreview(form)` emits a `--brand-on-primary` rule computed via
   `onPrimaryFor`.

Expected to FAIL until Issue #233 is implemented: `onPrimaryFor` (plus its
helpers) do not yet exist in static/main.js, and applyThemePreview does not
yet reference --brand-on-primary or call onPrimaryFor.
"""
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

import pytest

from tests.js_source import read_static_js

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tests.test_brand_teal_contrast import (
    contrast_ratio,
    WCAG_AA_MIN,
)

# Corpus shared with tests/test_theme_on_primary_contrast.py's hostile-color
# and hand-picked-default coverage, plus pure black/white edge cases.
COLOR_CORPUS = (
    "#7a7f4a",
    "#767676",
    "#8a6a3a",
    "#14b8a6",
    "#0e7268",
    "#000000",
    "#ffffff",
)


def _src():
    return read_static_js()


def _extract_function(src, name):
    """Extract the source of a top-level `function name(...) { ... }` declaration
    by brace-matching (handles nested braces inside the function body)."""
    m = re.search(r'function\s+' + re.escape(name) + r'\s*\([^)]*\)\s*\{', src)
    if not m:
        return None
    start = m.start()
    brace_start = m.end() - 1
    depth = 0
    for i in range(brace_start, len(src)):
        if src[i] == '{':
            depth += 1
        elif src[i] == '}':
            depth -= 1
            if depth == 0:
                return src[start:i + 1]
    return None


@pytest.mark.unit
def test_on_primary_for_js_matches_python_for_color_corpus():
    """The JS onPrimaryFor() helper (plus its linearize/relativeLuminance/
    contrastRatio dependencies) must exist in static/modules/color.js and must return
    exactly the same on-color as the Python _on_primary_for() for every
    color in COLOR_CORPUS."""
    if shutil.which("node") is None:
        pytest.skip("node binary is not available in this environment")

    color_module_path = pathlib.Path(__file__).parent.parent / "static" / "modules" / "color.js"
    color_module_url = color_module_path.resolve().as_uri()

    js_source = f"""import {{ onPrimaryFor }} from '{color_module_url}';
const corpus = {json.dumps(list(COLOR_CORPUS))};
const result = {{}};
corpus.forEach(c => {{ result[c] = onPrimaryFor(c); }});
console.log(JSON.stringify(result));
"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".mjs", delete=False) as f:
        f.write(js_source)
        js_path = f.name

    try:
        proc = subprocess.run(
            ["node", js_path], capture_output=True, text=True, timeout=30
        )
        assert proc.returncode == 0, (
            f"Running the extracted JS helpers via node failed "
            f"(exit code {proc.returncode}).\nstdout: {proc.stdout}\nstderr: {proc.stderr}"
        )
        js_results = json.loads(proc.stdout.strip().splitlines()[-1])
    finally:
        os.unlink(js_path)

    from api.routes import _on_primary_for

    for color in COLOR_CORPUS:
        py_value = _on_primary_for(color).lower()
        js_value = js_results[color].lower()
        assert js_value == py_value, (
            f"onPrimaryFor({color!r}) in static/main.js returned {js_value!r}, "
            f"but api/routes.py's _on_primary_for({color!r}) returned {py_value!r} "
            f"-- the JS and Python on-color derivations must be identical."
        )

        ratio = contrast_ratio(js_value, color)
        assert ratio >= WCAG_AA_MIN, (
            f"onPrimaryFor({color!r}) returned {js_value!r} with contrast ratio "
            f"{ratio:.2f} against {color!r}, below WCAG AA minimum {WCAG_AA_MIN}"
        )


@pytest.mark.unit
def test_apply_theme_preview_emits_brand_on_primary_token():
    """applyThemePreview(form) must compute and emit a --brand-on-primary CSS
    custom property via onPrimaryFor(), not just pass through the raw color
    picker values."""
    src = _src()
    body = _extract_function(src, "applyThemePreview")
    assert body is not None, "applyThemePreview not found in static/main.js"

    assert "--brand-on-primary" in body, (
        "applyThemePreview's preview <style> block omits the derived "
        "--brand-on-primary token -- it only emits the raw color picker "
        "values, so a previewed hostile brand_primary can leave the "
        "settings primary button's foreground text failing WCAG AA "
        "contrast (Issue #233)."
    )
    assert re.search(r'\bonPrimaryFor\s*\(', body), (
        "applyThemePreview's preview <style> block omits the derived "
        "--brand-on-primary token -- it must call onPrimaryFor() to derive "
        "a WCAG-AA-compliant foreground for the previewed brand_primary "
        "(Issue #233), but no call to onPrimaryFor() was found in its body."
    )
