"""Shared helpers for scope-aware remote filesystem operations.

Quadlets exist in two scopes:
  * ``global`` – rootful units under ``/etc/containers/systemd`` (require sudo)
  * ``user``   – rootless units under ``~/.config/containers/systemd``

Both the API routes and the background engines repeatedly derived the sudo
flag, the target directory, and the ``printf | tee`` write command from the
scope string. Those derivations live here so there is a single source of
truth.
"""
import shlex

from services.ssh_manager import pool

GLOBAL_QUADLET_DIR = "/etc/containers/systemd"
USER_QUADLET_DIR = "~/.config/containers/systemd"


def is_global_scope(scope: str) -> bool:
    """Return True for the global (rootful) scope, which requires sudo."""
    return scope == "global"


def quadlet_dir_for_scope(scope: str) -> str:
    """Return the systemd quadlet directory for the given scope."""
    return GLOBAL_QUADLET_DIR if is_global_scope(scope) else USER_QUADLET_DIR


async def write_remote_file(server_id: int, file_path: str, content: str, *, use_sudo: bool) -> None:
    """Write ``content`` to ``file_path`` on a remote server via ``printf | tee``.

    ``content`` is shell-quoted so arbitrary file bodies are written verbatim.
    When ``use_sudo`` is set the sudo is embedded in the ``tee`` stage of the
    pipeline (not applied to the whole pipeline), so the command is dispatched
    with ``use_sudo=False`` at the pool level.
    """
    tee_target = shlex.quote(file_path)
    tee = f"sudo tee {tee_target}" if use_sudo else f"tee {tee_target}"
    cmd = f"printf '%s' {shlex.quote(content)} | {tee} > /dev/null"
    await pool.execute_command(server_id, cmd, use_sudo=False)
