"""Shared reader for the frontend's static CSS sources (issue #447).

Structural tests assert on CSS source text. They must not care which file a given
rule lives in, so `static/style.css` can be split into separate files without
rewriting every assertion. This helper concatenates every non-vendor static CSS
file instead of reading one hardcoded path.
"""
import functools
import pathlib

STATIC_DIR = pathlib.Path(__file__).parent.parent / "static"
VENDOR_DIR = STATIC_DIR / "vendor"


def static_css_files():
    """Every non-vendor CSS file under static/, sorted for determinism."""
    return sorted(
        path
        for path in STATIC_DIR.rglob("*.css")
        if VENDOR_DIR not in path.parents
    )


@functools.lru_cache(maxsize=1)
def read_static_css():
    """Concatenated source of every non-vendor static CSS file."""
    return "\n\n".join(
        path.read_text(encoding="utf-8") for path in static_css_files()
    )
