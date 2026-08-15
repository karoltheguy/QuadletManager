"""Test whether the podman generator produces different output in rootful vs rootless mode.

This measures the fidelity gap cited in #337 condition 3: does running the
generator as root (global scope, current) produce different output than running
it as an unprivileged user (global scope, proposed)?

Run with: pytest -xvs tests/podman/test_validate_remote_real.py::test_rootful_generator_requires_sudo_to_match_runtime_behavior
"""

import pytest
import shlex
from services.ssh_manager import pool
from tests.podman.conftest import fixture_content

pytestmark = pytest.mark.podman


@pytest.mark.parametrize("fixture_file", ["e2e-sleep.container"])
async def test_rootful_generator_requires_sudo_to_match_runtime_behavior(podman_server, fixture_file):
    """Compare generator output when run as unprivileged user vs. as root.

    At daemon-reload time, the system generator runs as root. validate_remote
    currently runs it as the unprivileged SSH user, even for global scope.

    If the outputs differ, condition 3 of #337 is a real fidelity gap and a
    sudoers grant is needed. If they are identical, the `--user` flag alone
    carries the rootful/rootless distinction and sudo is not needed.
    """
    server_id = podman_server
    scratch_unprivileged = (await pool.execute_command(server_id, "mktemp -d", use_sudo=False)).strip()
    scratch_root = (await pool.execute_command(server_id, "mktemp -d", use_sudo=False)).strip()

    try:
        content = fixture_content(fixture_file)

        # Write the same file into both directories
        for scratch in [scratch_unprivileged, scratch_root]:
            await pool.execute_command(
                server_id,
                f"printf '%s' {shlex.quote(content)} | tee {shlex.quote(scratch)}/{fixture_file} > /dev/null",
                use_sudo=False
            )

        # Run generator as unprivileged user (current behavior for global scope)
        cmd_unprivileged = f"QUADLET_UNIT_DIRS={shlex.quote(scratch_unprivileged)} /usr/lib/systemd/system-generators/podman-system-generator -dryrun 2>&1 >/dev/null || true"
        output_unprivileged = await pool.execute_command(server_id, cmd_unprivileged, use_sudo=False)

        # Run generator as root (proposed behavior for global scope)
        cmd_root = f"QUADLET_UNIT_DIRS={shlex.quote(scratch_root)} /usr/lib/systemd/system-generators/podman-system-generator -dryrun 2>&1 >/dev/null || true"
        output_root = await pool.execute_command(server_id, cmd_root, use_sudo=True)

        print("\n--- OUTPUT AS UNPRIVILEGED USER ---")
        print(output_unprivileged or "(empty)")
        print("\n--- OUTPUT AS ROOT ---")
        print(output_root or "(empty)")

        # Compare
        if output_unprivileged.strip() == output_root.strip():
            print("\n✓ IDENTICAL: sudo is NOT required for fidelity")
            assert True
        else:
            print("\n✗ DIFFERENT: sudo IS required for fidelity")
            print("\nLines in root output but not unprivileged:")
            root_lines = set(output_root.strip().split('\n'))
            unprivileged_lines = set(output_unprivileged.strip().split('\n'))
            for line in sorted(root_lines - unprivileged_lines):
                print(f"  {line}")
            print("\nLines in unprivileged output but not root:")
            for line in sorted(unprivileged_lines - root_lines):
                print(f"  {line}")

    finally:
        for scratch in [scratch_unprivileged, scratch_root]:
            await pool.execute_command(server_id, f"rm -rf {shlex.quote(scratch)}", use_sudo=False)
