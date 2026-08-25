"""Shared reader for the frontend's static JavaScript sources (issue #388).

Structural tests assert on JS source text. They must not care which file a given
function lives in, so `static/main.js` can be split into ES modules without
rewriting every assertion. This helper concatenates every non-vendor static JS
file instead of reading one hardcoded path.
"""
import functools
import pathlib

STATIC_DIR = pathlib.Path(__file__).parent.parent / "static"
VENDOR_DIR = STATIC_DIR / "vendor"


def static_js_files():
    """Every non-vendor JavaScript file under static/, sorted for determinism."""
    return sorted(
        path
        for path in STATIC_DIR.rglob("*.js")
        if VENDOR_DIR not in path.parents
    )


@functools.lru_cache(maxsize=1)
def read_static_js():
    """Concatenated source of every non-vendor static JavaScript file."""
    return "\n\n".join(
        path.read_text(encoding="utf-8") for path in static_js_files()
    )
