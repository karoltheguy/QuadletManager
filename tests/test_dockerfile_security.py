import os
import pytest


def read_dockerfile_lines(filepath):
    with open(filepath, "r") as f:
        return [line.strip() for line in f]


@pytest.mark.unit
def test_dockerfile_runs_as_non_root_user():
    """Verify the runtime image drops to a non-root USER before the container's CMD runs."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dockerfile_path = os.path.join(base_dir, "Dockerfile")
    lines = read_dockerfile_lines(dockerfile_path)

    last_from_index = max(i for i, line in enumerate(lines) if line.startswith("FROM "))
    cmd_index = next(i for i, line in enumerate(lines) if line.startswith("CMD "))

    user_indices = [i for i, line in enumerate(lines) if line.startswith("USER ")]
    assert user_indices, "Dockerfile has no USER instruction; container runs as root"

    user_index = user_indices[-1]
    user_value = lines[user_index].split(None, 1)[1].strip()

    assert user_value != "root", "USER instruction must not set the user to root"
    assert last_from_index < user_index < cmd_index, (
        "USER instruction must be in the final image stage, before CMD"
    )
