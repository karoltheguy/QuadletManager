"""Shared reader for the frontend's static CSS sources (issue #447).

Structural tests assert on CSS source text. They must not care which file a given
rule lives in, so `static/style.css` can be split into separate files without
rewriting every assertion. This helper concatenates every non-vendor static CSS
file instead of reading one hardcoded path.
"""
import functools
import pathlib
import re

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


def strip_comments(css: str) -> str:
    """Remove every /* ... */ comment, including multi-line ones."""
    return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)


def rule_blocks(css: str) -> list[str]:
    """Split stripped CSS into top-level blocks and return them normalized.

    Walk the text tracking brace depth. A block ends at the '}' that returns depth to 0.
    An at-rule that ends in ';' at depth 0 (for example @import url(...);) is its own block.
    Nested at-rules such as @media { ... } are ONE block including their inner rules; do not
    descend into them.
    Normalize each block by collapsing every run of whitespace to a single space and stripping
    leading/trailing whitespace. Discard empty blocks.
    """
    blocks = []
    current = []
    depth = 0
    in_quote = None
    escape = False

    for char in css:
        if escape:
            current.append(char)
            escape = False
            continue

        if char == "\\":
            current.append(char)
            escape = True
            continue

        if in_quote:
            current.append(char)
            if char == in_quote:
                in_quote = None
            continue

        if char in ('"', "'"):
            in_quote = char
            current.append(char)
            continue

        if char == "{":
            depth += 1
            current.append(char)
        elif char == "}":
            depth -= 1
            current.append(char)
            if depth == 0:
                block_str = "".join(current)
                normalized = " ".join(block_str.split())
                if normalized:
                    blocks.append(normalized)
                current = []
        elif char == ";" and depth == 0:
            current.append(char)
            block_str = "".join(current)
            normalized = " ".join(block_str.split())
            if normalized:
                blocks.append(normalized)
            current = []
        else:
            current.append(char)

    if current:
        normalized = " ".join("".join(current).split())
        if normalized:
            blocks.append(normalized)

    return blocks
