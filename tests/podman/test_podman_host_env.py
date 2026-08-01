"""The canary. If these fail, nothing else in the suite is worth debugging.

Each test here guards one assumption the rest of the suite silently depends on,
and each has already failed for real at least once while this host image was
being built.
"""

import pytest

from services.quadlet_validator import _GENERATOR_PATHS
from services.ssh_manager import pool
from services.systemd_manager import ROOTLESS_ENV_PREFIX

pytestmark = pytest.mark.podman


async def test_ssh_reaches_the_expected_account(podman_server, podman_target):
    """Sanity-check the connection before blaming anything more interesting."""
    whoami = await pool.execute_command(podman_server, "whoami", use_sudo=False)
    assert whoami.strip() == podman_target["user"]


async def test_host_runs_podman_5(podman_server):
    """The entire premise. ubuntu-24.04 ships podman 4.9.3, which is why CI uses
    a pinned Fedora image rather than the runner's own podman."""
    version = await pool.execute_command(podman_server, "podman --version", use_sudo=False)
    assert version.strip().startswith("podman version 5."), (
        f"expected podman 5, got {version.strip()!r}. Quadlet behaviour and "
        ".pod support differ on 4.x."
    )


async def test_quadlet_generator_is_present(podman_server):
    """services/quadlet_validator.py probes exactly these two paths. With
    neither present it silently falls back to local-only INI validation, and
    test_validate_remote_real.py would pass while asserting nothing."""
    probe = "for p in " + " ".join(_GENERATOR_PATHS) + '; do if [ -x "$p" ]; then echo "$p"; break; fi; done'
    found = await pool.execute_command(podman_server, probe, use_sudo=False)
    assert found.strip() in _GENERATOR_PATHS, (
        f"no quadlet generator at any of {_GENERATOR_PATHS}"
    )


async def test_rootless_session_is_live(podman_server):
    """The linger canary, and the single most likely thing to be broken.

    Without /var/lib/systemd/linger/<user>, /run/user/<uid> does not exist for a
    non-interactive SSH session, so every command built with
    ROOTLESS_ENV_PREFIX returns empty output rather than an error, and the
    rootless half of the suite fails in ways that point nowhere near linger.
    """
    state = await pool.execute_command(
        podman_server,
        f"{ROOTLESS_ENV_PREFIX} systemctl --user is-system-running",
        use_sudo=False,
    )
    assert state.strip(), (
        "empty output from `systemctl --user`, which means XDG_RUNTIME_DIR "
        "points at nothing. Check that linger is enabled for this user."
    )
    # "degraded" is tolerated: it only means some unrelated user unit failed.
    assert state.strip() in {"running", "degraded", "starting"}, state


async def test_rootless_podman_is_usable(podman_server):
    """Rootless podman needs newuidmap/newgidmap to carry file capabilities.

    Fedora's *container* base image ships them without, unlike the host RPM, so
    Dockerfile.podman-host sets them explicitly. When that regresses the error
    is "should have setuid or have filecaps setuid", which reads like a linger
    problem and is not one.
    """
    out = await pool.execute_command(
        podman_server,
        f"{ROOTLESS_ENV_PREFIX} podman info --format '{{{{.Host.Security.Rootless}}}}'",
        use_sudo=False,
    )
    assert out.strip() == "true", f"rootless podman is not usable: {out.strip()!r}"


async def test_rootful_podman_is_usable(podman_server):
    """The global scope shells out to `sudo podman`, so the sudoers policy on
    the target has to actually permit it."""
    out = await pool.execute_command(
        podman_server, "podman info --format '{{.Host.Security.Rootless}}'", use_sudo=True
    )
    assert out.strip() == "false", f"rootful podman is not usable: {out.strip()!r}"


@pytest.mark.parametrize("scope", ["user", "global"])
async def test_test_image_is_preloaded(podman_server, scope):
    """The fixtures reference this image by name. It is baked into the host
    image and loaded into both stores at boot precisely so that no test run
    depends on a network pull or on quay.io being reachable."""
    from services.remote_fs import is_global_scope

    prefix = "" if is_global_scope(scope) else f"{ROOTLESS_ENV_PREFIX} "
    out = await pool.execute_command(
        podman_server,
        f"{prefix}podman image exists quay.io/quay/busybox:latest && echo present || echo missing",
        use_sudo=is_global_scope(scope),
    )
    assert out.strip() == "present", (
        f"busybox missing from the {scope} image store; "
        "load-test-image.service may have failed at boot"
    )
