"""Escaping helper for logging client-supplied values."""


def log_safe(value) -> str:
    """Escape control characters in a client-supplied value before logging it.

    Newlines, carriage returns and ANSI escapes would otherwise let a caller
    forge extra log lines. Escaping rather than stripping keeps the original
    bytes visible for debugging.
    """
    return str(value).encode("unicode_escape").decode("ascii")
