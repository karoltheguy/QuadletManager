"""Content-Security-Policy (CSP) header construction and nonce generation.

Issue #472: provides per-request script nonces and strict CSP directives
to mitigate cross-site scripting without breaking runtime theme overrides
or Monaco web workers.
"""

import secrets


def generate_nonce() -> str:
    """Return a cryptographically secure, fresh CSP nonce for a request."""
    return secrets.token_urlsafe(16)


def build_csp(nonce: str) -> str:
    """Return the full Content-Security-Policy header value for the given nonce.

    Non-obvious allowances:
      - style-src keeps 'unsafe-inline' because static/modules/theme.js creates a
        <style> element and sets its textContent at runtime, and several
        templates carry style= attributes. A nonce cannot cover either.
      - worker-src allows blob: because Monaco wraps its web workers in a blob
        URL when its base URL is cross-origin.
      - font-src allows data: because Monaco embeds its codicon icon font as a
        base64 data URL in vendor/monaco/vs/vs/editor/editor.main.css. Without
        it the editor renders with missing glyphs.
    """
    return (
        "default-src 'self'; "
        f"script-src 'self' 'nonce-{nonce}'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' data: https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "worker-src 'self' blob:; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none'"
    )
