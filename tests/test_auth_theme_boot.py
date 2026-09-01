"""Tests for issue #474: the auth pages' FOUC boot script reads the wrong key.

`static/auth_theme_boot.js` runs on the login and change-password pages, which
have no `data-theme-pref` attribute and no density handling, so it is a trimmed
counterpart to `static/theme_boot.js`. It must still read the same localStorage
key that `toggleTheme` writes, or a saved theme can never apply there.
"""
import os

import pytest

AUTH_BOOT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "static", "auth_theme_boot.js"
)


def _read_auth_boot():
    with open(AUTH_BOOT_PATH, encoding="utf-8") as f:
        return f.read()


@pytest.mark.unit
def test_auth_boot_reads_the_key_toggle_theme_writes():
    """The auth boot script must read 'qm-theme-override', not the dead 'qm-theme'."""
    boot = _read_auth_boot()
    assert "'qm-theme-override'" in boot, (
        "auth_theme_boot.js must read the 'qm-theme-override' key, which is the "
        "only theme key toggleTheme writes (static/modules/theme.js)"
    )
    assert "'qm-theme'" not in boot, (
        "auth_theme_boot.js must not read 'qm-theme'; nothing in the codebase "
        "writes that key"
    )


@pytest.mark.unit
def test_auth_boot_sets_data_theme_on_the_root_element():
    """Reading the key is only useful if it still lands on <html data-theme>."""
    boot = _read_auth_boot()
    assert "dataset.theme" in boot, (
        "auth_theme_boot.js must set data-theme on the root element"
    )
