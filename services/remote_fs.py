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
import posixpath
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


def ensure_within_quadlet_dir(file_path: str, scope: str) -> str:
    """Confine ``file_path`` to the quadlet directory for ``scope`` before it
    ever reaches a remote command.

    The sudoers rules shipped with this project look confined because every
    line ends in ``/etc/containers/systemd/*``. It isn't. sudo matches command
    arguments against that pattern with fnmatch and *without* ``FNM_PATHNAME``,
    so the glob's ``*`` happily matches ``/`` too, and a caller-supplied
    ``..`` segment walks straight out of the directory the pattern was meant
    to pin. The sudoers glob narrows the surface but does not confine
    anything by itself; this function is what actually does.

    The check is deliberately lexical: normalize with ``posixpath.normpath``
    (never ``os.path`` and never ``realpath``, since these strings name paths
    on a remote host and resolving them against the local filesystem would
    describe the wrong machine entirely) and then require that the
    normalized path's parent directory equals the scope's quadlet directory
    exactly. That one comparison rejects traversal, the directory itself,
    subdirectories, and string-prefix siblings like
    ``/etc/containers/systemd-evil`` alike.

    Residual risk, stated honestly: this is a lexical check on a string, not
    a check on the filesystem it names. If a symlink already planted inside
    the quadlet directory on the remote host points somewhere else, this
    function has no way to see that and will happily approve the link's own
    path. Catching that would require a stat/readlink check performed on the
    remote host itself, not here.
    """
    if not file_path.startswith("/"):
        raise ValueError(f"Path is not absolute: {file_path}")

    normalized = posixpath.normpath(file_path)
    parent = posixpath.dirname(normalized)

    if is_global_scope(scope):
        expected_parent = GLOBAL_QUADLET_DIR
    else:
        if not (parent.startswith("/") and parent.endswith(f"/{USER_QUADLET_SUBDIR}")):
            raise ValueError(
                f"Path is outside the quadlet directory for scope {scope!r}: {file_path}"
            )
        expected_parent = parent

    if parent != expected_parent:
        raise ValueError(
            f"Path is outside the quadlet directory for scope {scope!r}: {file_path}"
        )

    return normalized


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
