from unittest.mock import AsyncMock, patch

import pytest

from services.quadlet_validator import parse_generator_stderr, validate_remote
from services.ssh_manager import SSHCommandError


@pytest.mark.unit
def test_ignored_unsupported_key_is_warning():
    line = (
        "Error converting unit file, ignoring: unsupported key 'Pull' "
        "in group 'Container' in /tmp/qv/test.container"
    )
    issues = parse_generator_stderr(line)
    assert len(issues) == 1
    issue = issues[0]
    assert issue["level"] == "warning"
    assert issue["key"] == "Pull"
    assert "unsupported key 'Pull' in group 'Container'" in issue["message"]


@pytest.mark.unit
def test_parse_error_without_ignoring_is_error():
    line = "error parsing '/tmp/qv/test.container': invalid line: xyz"
    issues = parse_generator_stderr(line)
    assert len(issues) == 1
    issue = issues[0]
    assert issue["level"] == "error"
    assert issue["key"] is None


@pytest.mark.unit
def test_multiple_lines_produce_issues_in_order():
    warning_line = (
        "Error converting unit file, ignoring: unsupported key 'Pull' "
        "in group 'Container' in /tmp/qv/test.container"
    )
    error_line = "error parsing '/tmp/qv/test.container': invalid line: xyz"
    text = f"{warning_line}\n{error_line}"

    issues = parse_generator_stderr(text)

    assert len(issues) == 2
    assert issues[0]["level"] == "warning"
    assert issues[0]["key"] == "Pull"
    assert issues[1]["level"] == "error"
    assert issues[1]["key"] is None


@pytest.mark.unit
def test_empty_string_returns_no_issues():
    assert parse_generator_stderr("") == []


@pytest.mark.unit
def test_whitespace_only_returns_no_issues():
    assert parse_generator_stderr("   \n  \n") == []


# --- validate_remote --------------------------------------------------------
#
# validate_remote() is expected to, on the happy path:
#   1. probe the remote host for a podman quadlet generator
#   2. mktemp a scratch directory
#   3. write the unit file into that scratch directory
#   4. run the generator with -dryrun against the scratch directory
#   5. parse any generator stderr output into issues
#   6. rm -rf the scratch directory regardless of outcome
#
# Since the implementation doesn't exist yet, tests key the execute_command
# mock off distinguishing substrings ("mktemp", "-dryrun", "rm -rf") rather
# than call order, and treat any other command as the generator probe.

MKTEMP_DIR = "/tmp/qv-test123"


def _make_execute_command(probe_return="", dryrun_return="", dryrun_raises=None):
    """Build an AsyncMock side_effect for pool.execute_command keyed on command content."""

    async def _side_effect(server_id, command, use_sudo=False, timeout=30.0):
        if "mktemp" in command:
            return MKTEMP_DIR
        if "-dryrun" in command:
            if dryrun_raises is not None:
                raise dryrun_raises
            return dryrun_return
        if "rm -rf" in command:
            return ""
        # Anything else is treated as the generator probe.
        return probe_return

    return AsyncMock(side_effect=_side_effect)


@pytest.mark.unit
async def test_validate_remote_clean_run_is_valid():
    execute_command = _make_execute_command(
        probe_return="/usr/lib/systemd/system-generators/podman-system-generator",
        dryrun_return="",
    )
    write_remote_file = AsyncMock()

    with patch("services.quadlet_validator.pool") as mock_pool, \
            patch("services.quadlet_validator.write_remote_file", write_remote_file):
        mock_pool.execute_command = execute_command

        result = await validate_remote(1, "[Container]\nImage=foo\n", "test.container", "system")

    assert result == {"valid": True, "local_only": False, "issues": []}

    write_remote_file.assert_awaited_once()
    call = write_remote_file.await_args
    assert call.args[1] == f"{MKTEMP_DIR}/test.container" or call.kwargs.get("file_path") == f"{MKTEMP_DIR}/test.container"

    rm_calls = [
        c for c in execute_command.await_args_list
        if "rm -rf" in c.args[1] and MKTEMP_DIR in c.args[1]
    ]
    assert len(rm_calls) == 1


@pytest.mark.unit
async def test_validate_remote_warning_only_is_still_valid():
    dryrun_output = (
        "Error converting unit file, ignoring: unsupported key 'Pull' "
        f"in group 'Container' in {MKTEMP_DIR}/test.container"
    )
    execute_command = _make_execute_command(
        probe_return="/usr/lib/systemd/system-generators/podman-system-generator",
        dryrun_return=dryrun_output,
    )
    with patch("services.quadlet_validator.pool") as mock_pool, \
            patch("services.quadlet_validator.write_remote_file", AsyncMock()):
        mock_pool.execute_command = execute_command

        result = await validate_remote(1, "[Container]\nImage=foo\n", "test.container", "system")

    assert result["valid"] is True
    assert result["local_only"] is False
    assert len(result["issues"]) == 1
    assert result["issues"][0]["level"] == "warning"
    assert result["issues"][0]["key"] == "Pull"


@pytest.mark.unit
async def test_validate_remote_hard_error_is_invalid():
    dryrun_output = f"error parsing '{MKTEMP_DIR}/test.container': invalid line: xyz"
    execute_command = _make_execute_command(
        probe_return="/usr/lib/systemd/system-generators/podman-system-generator",
        dryrun_return=dryrun_output,
    )
    with patch("services.quadlet_validator.pool") as mock_pool, \
            patch("services.quadlet_validator.write_remote_file", AsyncMock()):
        mock_pool.execute_command = execute_command

        result = await validate_remote(1, "[Container]\n", "test.container", "system")

    assert result["valid"] is False
    assert len(result["issues"]) == 1
    assert result["issues"][0]["level"] == "error"


@pytest.mark.unit
async def test_validate_remote_falls_back_to_local_when_no_generator():
    execute_command = _make_execute_command(probe_return="")
    write_remote_file = AsyncMock()

    with patch("services.quadlet_validator.pool") as mock_pool, \
            patch("services.quadlet_validator.write_remote_file", write_remote_file):
        mock_pool.execute_command = execute_command

        result = await validate_remote(1, "[Container]\n", "test.container", "system")

    assert result["valid"] is False
    assert result["local_only"] is True
    assert len(result["issues"]) == 1
    assert result["issues"][0]["level"] == "error"

    write_remote_file.assert_not_awaited()
    dryrun_calls = [
        c for c in execute_command.await_args_list if "-dryrun" in c.args[1]
    ]
    assert len(dryrun_calls) == 0


@pytest.mark.unit
async def test_validate_remote_cleans_up_scratch_dir_on_dryrun_failure():
    execute_command = _make_execute_command(
        probe_return="/usr/lib/systemd/system-generators/podman-system-generator",
        dryrun_raises=SSHCommandError("boom", exit_status=1, stderr="boom"),
    )

    with patch("services.quadlet_validator.pool") as mock_pool, \
            patch("services.quadlet_validator.write_remote_file", AsyncMock()):
        mock_pool.execute_command = execute_command

        try:
            await validate_remote(1, "[Container]\nImage=foo\n", "test.container", "system")
        except SSHCommandError:
            pass

    rm_calls = [
        c for c in execute_command.await_args_list
        if "rm -rf" in c.args[1] and MKTEMP_DIR in c.args[1]
    ]
    assert len(rm_calls) == 1


@pytest.mark.unit
async def test_validate_remote_user_scope_passes_user_flag():
    execute_command = _make_execute_command(
        probe_return="/usr/lib/systemd/system-generators/podman-system-generator",
        dryrun_return="",
    )
    with patch("services.quadlet_validator.pool") as mock_pool, \
            patch("services.quadlet_validator.write_remote_file", AsyncMock()):
        mock_pool.execute_command = execute_command

        await validate_remote(1, "[Container]\nImage=foo\n", "test.container", "user")

    dryrun_calls = [c for c in execute_command.await_args_list if "-dryrun" in c.args[1]]
    assert len(dryrun_calls) == 1
    assert "--user" in dryrun_calls[0].args[1]


@pytest.mark.unit
async def test_validate_remote_global_scope_omits_user_flag():
    execute_command = _make_execute_command(
        probe_return="/usr/lib/systemd/system-generators/podman-system-generator",
        dryrun_return="",
    )
    with patch("services.quadlet_validator.pool") as mock_pool, \
            patch("services.quadlet_validator.write_remote_file", AsyncMock()):
        mock_pool.execute_command = execute_command

        await validate_remote(1, "[Container]\nImage=foo\n", "test.container", "system")

    dryrun_calls = [c for c in execute_command.await_args_list if "-dryrun" in c.args[1]]
    assert len(dryrun_calls) == 1
    assert "--user" not in dryrun_calls[0].args[1]


# --- real Podman 5.8.4 generator output shapes -----------------------------
#
# Smoke-testing against the real generator revealed:
#   - stderr lines are prefixed "quadlet-generator[PID]: "
#   - valid files still emit informational "Loading source unit file <path>"
#     lines, which are noise, not issues
#   - a trailing summary line "processing encountered some errors" is noise
#   - unsupported-key lines no longer say "ignoring"


@pytest.mark.unit
def test_real_clean_run_loading_line_is_noise():
    line = (
        "quadlet-generator[1312195]: Loading source unit file "
        "/tmp/qv-clean/clean.container"
    )
    assert parse_generator_stderr(line) == []


@pytest.mark.unit
def test_real_mixed_output_parses_errors_only():
    text = (
        "quadlet-generator[1310995]: Loading source unit file "
        "/tmp/qv-smoke/badsection.container\n"
        "quadlet-generator[1310995]: Loading source unit file "
        "/tmp/qv-smoke/good-ish.container\n"
        "quadlet-generator[1310995]: converting \"badsection.container\": "
        "no Image or Rootfs key specified\n"
        "quadlet-generator[1310995]: converting \"good-ish.container\": "
        "unsupported key 'BogusKey' in group 'Container' in "
        "/tmp/qv-smoke/good-ish.container\n"
        "quadlet-generator[1310995]: processing encountered some errors"
    )

    issues = parse_generator_stderr(text)

    assert len(issues) == 2

    assert issues[0]["level"] == "error"
    assert issues[0]["key"] is None
    assert "no Image or Rootfs key specified" in issues[0]["message"]
    assert "quadlet-generator" not in issues[0]["message"]

    assert issues[1]["level"] == "error"
    assert issues[1]["key"] == "BogusKey"
    assert "quadlet-generator" not in issues[1]["message"]


@pytest.mark.unit
def test_prefix_stripped_from_message():
    line = (
        "quadlet-generator[1310995]: converting \"badsection.container\": "
        "no Image or Rootfs key specified"
    )
    issues = parse_generator_stderr(line)
    assert len(issues) == 1
    assert not issues[0]["message"].startswith("quadlet-generator[")


@pytest.mark.unit
async def test_validate_remote_real_clean_stderr_is_valid():
    dryrun_output = (
        "quadlet-generator[1312195]: Loading source unit file "
        "/tmp/qv-test123/test.container"
    )
    execute_command = _make_execute_command(
        probe_return="/usr/lib/systemd/system-generators/podman-system-generator",
        dryrun_return=dryrun_output,
    )
    with patch("services.quadlet_validator.pool") as mock_pool, \
            patch("services.quadlet_validator.write_remote_file", AsyncMock()):
        mock_pool.execute_command = execute_command

        result = await validate_remote(1, "[Container]\nImage=foo\n", "test.container", "system")

    assert result == {"valid": True, "local_only": False, "issues": []}
