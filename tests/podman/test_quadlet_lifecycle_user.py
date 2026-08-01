"""Rootless quadlet lifecycle, against $HOME/.config/containers/systemd.

The scope most likely to break in the field, and the one that was never
exercised before this suite: it depends on linger, on XDG_RUNTIME_DIR, and on
rootless podman having a working newuidmap.
"""

import pytest

from tests.podman.lifecycle_steps import assert_full_lifecycle

pytestmark = pytest.mark.podman


# The global 120s ceiling in pytest.ini is tight for daemon-reload plus a
# container start plus polling. Raised here rather than globally, since that
# ceiling exists to turn wedged tests into named failures.
@pytest.mark.timeout(300)
async def test_user_scope_quadlet_lifecycle(podman_server):
    await assert_full_lifecycle(podman_server, "user")
