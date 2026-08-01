"""Rootful quadlet lifecycle, against /etc/containers/systemd.

Every step here goes through sudo. On the loopback target this writes to the
developer's real system directory, which is why the e2e- prefix guard in
conftest.py is not optional.
"""

import pytest

from tests.podman.lifecycle_steps import assert_full_lifecycle

pytestmark = pytest.mark.podman


@pytest.mark.timeout(300)
async def test_global_scope_quadlet_lifecycle(podman_server):
    await assert_full_lifecycle(podman_server, "global")
