"""Validation helpers for interpreting quadlet-generator diagnostic output."""

import os
import re
import shlex

from services.quadlet_parser import QuadletValidationError, validate_quadlet_syntax
from services.remote_fs import is_global_scope, quadlet_dir_for_scope, write_remote_file
from services.ssh_manager import pool

_KEY_RE = re.compile(r"key '([^']+)'")
_UNIT_RE = re.compile(r'converting "([^"]+)"')
_GENERATOR_PREFIX_RE = re.compile(r"^quadlet-generator\[\d+\]:\s*")

_GENERATOR_PATHS = (
    "/usr/lib/systemd/system-generators/podman-system-generator",
    "/usr/libexec/podman/quadlet",
)


async def validate_remote(server_id: int, content: str, file_name: str, scope: str) -> dict:
    """Validate a quadlet unit file against a remote server's generator.

    Probes the remote host for a podman quadlet generator binary. When one is
    found, the unit file is written to a scratch directory and the generator
    is run with ``-dryrun`` against it; any stderr output is parsed into
    issues via :func:`parse_generator_stderr`. When no generator is found on
    the remote host, falls back to local INI-level syntax validation via
    :func:`services.quadlet_parser.validate_quadlet_syntax`.
    """
    probe_cmd = (
        "for p in " + " ".join(_GENERATOR_PATHS) + '; do if [ -x "$p" ]; then echo "$p"; break; fi; done'
    )
    generator = (await pool.execute_command(server_id, probe_cmd, use_sudo=False)).strip()

    if not generator:
        quadlet_type = file_name.rsplit(".", 1)[-1] if "." in file_name else "container"
        issues = []
        valid = True
        try:
            validate_quadlet_syntax(content, quadlet_type)
        except QuadletValidationError as exc:
            valid = False
            issues.append({"level": "error", "message": str(exc), "key": None})
        return {"valid": valid, "local_only": True, "issues": issues}

    scratch = (await pool.execute_command(server_id, "mktemp -d", use_sudo=False)).strip()
    try:
        use_sudo = is_global_scope(scope)
        source_dir = await quadlet_dir_for_scope(server_id, scope)
        find_cmd = f"find {shlex.quote(source_dir)} -type f -maxdepth 1"
        listing = await pool.execute_command(server_id, find_cmd, use_sudo=use_sudo)
        for source_path in listing.strip().splitlines():
            source_path = source_path.strip()
            if not source_path:
                continue
            file_content = await pool.execute_command(
                server_id, f"cat {shlex.quote(source_path)}", use_sudo=use_sudo
            )
            await write_remote_file(
                server_id, f"{scratch}/{os.path.basename(source_path)}", file_content, use_sudo=False
            )

        await write_remote_file(server_id, f"{scratch}/{file_name}", content, use_sudo=False)

        user_flag = " --user" if scope == "user" else ""
        dryrun_cmd = (
            f"QUADLET_UNIT_DIRS={shlex.quote(scratch)} {generator} -dryrun{user_flag} 2>&1 >/dev/null || true"
        )
        output = await pool.execute_command(server_id, dryrun_cmd, use_sudo=False)

        issues = parse_generator_stderr(output, file_name)
        valid = not any(issue["level"] == "error" for issue in issues)
        return {"valid": valid, "local_only": False, "issues": issues}
    finally:
        if scratch:
            await pool.execute_command(server_id, f"rm -rf {shlex.quote(scratch)}", use_sudo=False)


def parse_generator_stderr(text: str, file_name: str) -> list:
    """Parse stderr output from the systemd quadlet generator into issue dicts.

    Only lines attributed to ``file_name`` (via ``converting "<unit>": ...``)
    or unattributed lines are kept; lines attributed to other units in the
    scratch directory are dropped.

    Each issue dict has keys: level, message, key.
    """
    issues = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        line = _GENERATOR_PREFIX_RE.sub("", line)
        if line.startswith("Loading source unit file") or line == "processing encountered some errors":
            continue
        unit_match = _UNIT_RE.search(line)
        if unit_match and unit_match.group(1) != file_name:
            continue
        match = _KEY_RE.search(line)
        key = match.group(1) if match else None
        level = "warning" if "ignoring" in line else "error"
        issues.append({"level": level, "message": line, "key": key})
    return issues
