"""Unit tests for services.remote_fs.ensure_within_quadlet_dir (issue #289, part 2).

`ensure_within_quadlet_dir(file_path, scope)` must accept only a path that
names a file DIRECTLY inside the quadlet directory for the given scope, and
reject everything else (traversal, siblings, subdirectories, the directory
itself, relative paths).
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from services.remote_fs import GLOBAL_QUADLET_DIR, USER_QUADLET_SUBDIR


@pytest.mark.unit
def test_ordinary_global_path_is_accepted_and_normalized():
    from services.remote_fs import ensure_within_quadlet_dir

    result = ensure_within_quadlet_dir("/etc/containers/systemd/web.container", "global")
    assert result == "/etc/containers/systemd/web.container"


@pytest.mark.unit
def test_ordinary_user_scope_path_is_accepted():
    from services.remote_fs import ensure_within_quadlet_dir

    path = f"/home/carol/{USER_QUADLET_SUBDIR}/web.container"
    result = ensure_within_quadlet_dir(path, "user")
    assert result == path


@pytest.mark.unit
def test_dotdot_traversal_out_of_global_dir_is_rejected():
    from services.remote_fs import ensure_within_quadlet_dir

    with pytest.raises(ValueError):
        ensure_within_quadlet_dir("/etc/containers/systemd/../../etc/shadow", "global")


@pytest.mark.unit
def test_plain_outside_path_is_rejected():
    from services.remote_fs import ensure_within_quadlet_dir

    with pytest.raises(ValueError):
        ensure_within_quadlet_dir("/etc/shadow", "global")


@pytest.mark.unit
def test_prefix_sibling_directory_is_rejected_not_just_string_prefix_matched():
    """/etc/containers/systemd-evil starts with the quadlet dir as a string
    prefix but is not the quadlet dir itself; the dirname comparison must
    reject it."""
    from services.remote_fs import ensure_within_quadlet_dir

    with pytest.raises(ValueError):
        ensure_within_quadlet_dir("/etc/containers/systemd-evil/x.container", "global")


@pytest.mark.unit
def test_path_in_a_subdirectory_of_quadlet_dir_is_rejected():
    from services.remote_fs import ensure_within_quadlet_dir

    with pytest.raises(ValueError):
        ensure_within_quadlet_dir("/etc/containers/systemd/sub/web.container", "global")


@pytest.mark.unit
def test_relative_path_is_rejected():
    from services.remote_fs import ensure_within_quadlet_dir

    with pytest.raises(ValueError):
        ensure_within_quadlet_dir("etc/containers/systemd/web.container", "global")


@pytest.mark.unit
def test_the_quadlet_directory_itself_is_rejected():
    from services.remote_fs import ensure_within_quadlet_dir

    with pytest.raises(ValueError):
        ensure_within_quadlet_dir("/etc/containers/systemd", "global")


@pytest.mark.unit
def test_innocuous_dot_segment_is_normalized_and_accepted():
    from services.remote_fs import ensure_within_quadlet_dir

    result = ensure_within_quadlet_dir("/etc/containers/systemd/./web.container", "global")
    assert result == "/etc/containers/systemd/web.container"
