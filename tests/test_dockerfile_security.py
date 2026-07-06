import os
import re
import stat

import pytest


def read_dockerfile_lines(filepath):
    with open(filepath, "r") as f:
        return [line.strip() for line in f]


@pytest.mark.unit
def test_dockerfile_hands_off_to_entrypoint_before_cmd():
    """Verify the runtime image defers to entrypoint.sh (which drops to a
    non-root user) rather than a static USER instruction, so a pre-existing
    volume's ownership can be fixed before the app's CMD runs (see #162)."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dockerfile_path = os.path.join(base_dir, "Dockerfile")
    lines = read_dockerfile_lines(dockerfile_path)

    last_from_index = max(i for i, line in enumerate(lines) if line.startswith("FROM "))
    cmd_index = next(i for i, line in enumerate(lines) if line.startswith("CMD "))

    entrypoint_indices = [i for i, line in enumerate(lines) if line.startswith("ENTRYPOINT ")]
    assert entrypoint_indices, "Dockerfile has no ENTRYPOINT instruction"

    entrypoint_index = entrypoint_indices[-1]
    assert last_from_index < entrypoint_index < cmd_index, (
        "ENTRYPOINT must be in the final image stage, before CMD"
    )
    assert "entrypoint.sh" in lines[entrypoint_index]

    user_lines = [line for line in lines if line.startswith("USER ")]
    assert not any(line.split(None, 1)[1].strip() == "root" for line in user_lines), (
        "Dockerfile must not explicitly set USER root"
    )


@pytest.mark.unit
def test_entrypoint_fixes_ownership_and_drops_to_non_root():
    """Verify entrypoint.sh reconciles /data ownership then hands off to a
    non-root user via gosu/su-exec before exec'ing the container's CMD, so
    the app process itself never runs as root."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    entrypoint_path = os.path.join(base_dir, "entrypoint.sh")

    assert os.path.isfile(entrypoint_path), "entrypoint.sh is missing"
    assert os.stat(entrypoint_path).st_mode & stat.S_IXUSR, (
        "entrypoint.sh must be executable"
    )

    content = open(entrypoint_path).read()

    assert re.search(r"chown\s+-R\s+\S+\s+/data", content), (
        "entrypoint.sh must fix /data ownership before handoff"
    )

    dropper = re.search(r"\b(gosu|su-exec)\s+(\S+)", content)
    assert dropper, "entrypoint.sh must drop privileges via gosu/su-exec"
    assert dropper.group(2) != "root", "entrypoint.sh must not drop to root"
