"""Shared helpers for scope-aware remote filesystem operations.

Quadlets exist in two scopes:
  * ``global`` – rootful units under ``/etc/containers/systemd`` (require sudo)
  * ``user``   – rootless units under ``$HOME/.config/containers/systemd``

Both the API routes and the background engines repeatedly derived the sudo
flag, the target directory, and the ``printf | tee`` write command from the
scope string. Those derivations live here so there is a single source of
truth.

Remote paths must always be absolute. The user directory is resolved from
the remote ``$HOME`` rather than spelled ``~/...``, because every consumer
that passes a path through ``shlex.quote()`` would otherwise send a literal
``~`` the remote shell never expands.
"""
import shlex

from services.ssh_manager import pool

GLOBAL_QUADLET_DIR = "/etc/containers/systemd"
# The user quadlet directory, relative to the remote user's home.
USER_QUADLET_SUBDIR = ".config/containers/systemd"


def is_global_scope(scope: str) -> bool:
    """Return True for the global (rootful) scope, which requires sudo."""
    return scope == "global"


async def remote_home_dir(server_id: int) -> str:
    """Return the absolute home directory of the SSH user on a remote server."""
    home = (await pool.execute_command(server_id, 'printf %s "$HOME"', use_sudo=False)).strip()
    if not home.startswith("/"):
        raise ValueError(
            f"Could not resolve remote home directory on server {server_id}: {home!r}"
        )
    return home


async def quadlet_dir_for_scope(server_id: int, scope: str) -> str:
    """Return the absolute systemd quadlet directory for the given scope."""
    if is_global_scope(scope):
        return GLOBAL_QUADLET_DIR
    return f"{await remote_home_dir(server_id)}/{USER_QUADLET_SUBDIR}"


async def write_remote_file(server_id: int, file_path: str, content: str, *, use_sudo: bool) -> None:
    """Write ``content`` to ``file_path`` on a remote server via ``printf | tee``.

    ``file_path`` must be absolute (see module docstring). ``content`` is
    shell-quoted so arbitrary file bodies are written verbatim. When
    ``use_sudo`` is set the sudo is embedded in the ``tee`` stage of the
    pipeline (not applied to the whole pipeline), so the command is dispatched
    with ``use_sudo=False`` at the pool level.
    """
    tee_target = shlex.quote(file_path)
    tee = f"sudo tee {tee_target}" if use_sudo else f"tee {tee_target}"
    cmd = f"printf '%s' {shlex.quote(content)} | {tee} > /dev/null"
    await pool.execute_command(server_id, cmd, use_sudo=False)
