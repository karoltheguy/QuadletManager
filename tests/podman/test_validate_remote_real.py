"""First real exercise of the quadlet generator and parse_generator_stderr.

Until this suite existed, `services/quadlet_validator.py` always took its "no
generator found" fallback in tests, so `parse_generator_stderr` had never seen
output from an actual generator and `local_only` was always True.

These tests do not install anything into a quadlet directory: validate_remote
writes into its own `mktemp -d` scratch and removes it in a finally. So there is
nothing here for the e2e- teardown to clean up.
"""

import shlex

import pytest

from services.quadlet_validator import validate_remote
from services.remote_fs import is_global_scope, write_remote_file
from services.ssh_manager import pool
from tests.podman.conftest import ensure_quadlet_dir, fixture_content

pytestmark = pytest.mark.podman

VALID_FIXTURES = [
    "e2e-sleep.container",
    "e2e-health.container",
    "e2e-test.volume",
    "e2e-test.network",
    "e2e-test.pod",
]


@pytest.mark.parametrize("scope", ["user", "global"])
async def test_validation_uses_the_real_generator(podman_server, scope):
    """local_only=False is the whole point: it proves the generator was found
    and run, rather than the INI-level fallback having quietly stood in."""
    result = await validate_remote(
        podman_server, fixture_content("e2e-sleep.container"), "e2e-sleep.container", scope
    )
    assert result["local_only"] is False, (
        "validate_remote fell back to local-only validation, which means no "
        "generator was found at either of _GENERATOR_PATHS"
    )
    assert result["valid"] is True, result["issues"]


@pytest.mark.parametrize("file_name", VALID_FIXTURES)
async def test_valid_fixtures_produce_no_errors(podman_server, file_name):
    """Every fixture the rest of the suite installs must survive the generator.
    A fixture that silently fails to convert would make later tests fail in
    places that have nothing to do with the cause."""
    result = await validate_remote(
        podman_server, fixture_content(file_name), file_name, "user"
    )
    errors = [issue for issue in result["issues"] if issue["level"] == "error"]
    assert errors == [], f"{file_name} did not convert cleanly: {errors}"
    assert result["valid"] is True


@pytest.mark.parametrize("scope", ["user", "global"])
async def test_broken_fixture_yields_a_keyed_error(podman_server, scope):
    """The real generator's diagnostic must survive parsing with its key intact.

    podman 5.8.4 emits, on stderr:

        quadlet-generator[N]: converting "e2e-broken.container": unsupported key
        'ThisKeyDoesNotExist' in group 'Container' in /path/e2e-broken.container

    parse_generator_stderr extracts the quoted key via `key '([^']+)'`, and the
    surrounding "Loading source unit file" and "processing encountered some
    errors" lines are dropped. If podman ever changes that phrasing, the key
    goes None and the editor's inline diagnostics stop pointing at a line --
    which is exactly the regression this test is here to catch.
    """
    result = await validate_remote(
        podman_server, fixture_content("e2e-broken.container"), "e2e-broken.container", scope
    )

    assert result["local_only"] is False
    assert result["valid"] is False, "an unsupported key should not validate"

    errors = [issue for issue in result["issues"] if issue["level"] == "error"]
    assert len(errors) == 1, f"expected exactly one error, got {result['issues']}"

    assert errors[0]["key"] == "ThisKeyDoesNotExist", (
        f"key extraction failed against real generator output: {errors[0]}"
    )
    assert "unsupported key" in errors[0]["message"]


async def test_noise_lines_are_not_reported_as_issues(podman_server):
    """The generator brackets its real diagnostics with two lines that are not
    problems. Both must be filtered, or every validation of a valid file would
    show phantom issues in the editor."""
    result = await validate_remote(
        podman_server, fixture_content("e2e-sleep.container"), "e2e-sleep.container", "user"
    )
    messages = " ".join(issue["message"] for issue in result["issues"])
    assert "Loading source unit file" not in messages
    assert "processing encountered some errors" not in messages


@pytest.mark.parametrize("scope", ["user", "global"])
async def test_validate_resolves_pod_reference_in_real_directory(podman_server, scope):
    """A container that references an existing pod on the server validates
    cleanly because the generator sees the real quadlet directory.

    validate_remote currently writes into an empty `mktemp -d` scratch, so a
    Pod= reference to a unit that only exists in the real quadlet directory
    cannot resolve there.
    """
    directory = await ensure_quadlet_dir(podman_server, scope)
    pod_path = f"{directory}/e2e-test.pod"
    await write_remote_file(
        podman_server, pod_path, fixture_content("e2e-test.pod"), use_sudo=is_global_scope(scope)
    )
    try:
        container_content = (
            "[Container]\n"
            "Image=busybox\n"
            "Pod=e2e-test.pod\n"
        )
        result = await validate_remote(
            podman_server, container_content, "test-pod-ref.container", scope
        )
        assert result["valid"] is True, result["issues"]
    finally:
        await pool.execute_command(
            podman_server,
            f"rm -f {shlex.quote(pod_path)}",
            use_sudo=is_global_scope(scope),
        )
