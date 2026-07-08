import logging
import re
import shlex
from services.ssh_manager import pool
from services.remote_fs import is_global_scope


logger = logging.getLogger("quadlet-manager.systemd")

# Allowlist for systemd unit names (supports template instances like foo@bar.service).
# Anything outside this set is rejected before the value ever reaches a shell.
_UNIT_NAME_RE = re.compile(r"^[a-zA-Z0-9_@\-\.:\\]+$")

async def systemctl_action(server_id: int, action: str, unit_name: str, scope: str = 'global', allow_failure: bool = False):
    """
    Executes a systemctl action (start, stop, restart, status) on a unit.
    Applies user-level systemctl if scope is 'user', otherwise global.

    Args:
        allow_failure: When True, non-zero exit codes are logged and returned
                       as an error string rather than raising an exception.
                       Useful for daemon-reload / restart in the save flow,
                       where the file was already written successfully and we
                       don't want a restart hiccup to show as a save failure.
    """
    allowed_actions = ['start', 'stop', 'restart', 'status', 'daemon-reload']
    if action not in allowed_actions:
        raise ValueError(f"Invalid systemctl action: {action}")
        
    use_sudo = is_global_scope(scope)
    cmd_prefix = "systemctl"
    if scope == 'user':
        cmd_prefix = "systemctl --user"
        
    cmd = f"{cmd_prefix} {action}"
    if action != 'daemon-reload' and unit_name:
        if not _UNIT_NAME_RE.match(unit_name):
            raise ValueError(f"Invalid unit name: {unit_name!r}")
        cmd += f" {shlex.quote(unit_name)}"

    try:
        logger.info(f"Running '{cmd}' on server_id={server_id} (sudo={use_sudo})")
        return await pool.execute_command(server_id, cmd, use_sudo=use_sudo)
    except Exception as e:
        if allow_failure:
            logger.warning(f"Systemctl action '{action}' finished with non-zero exit (allow_failure=True): {e}")
            return "(warning: action did not complete cleanly, see server logs)"
        logger.error(f"Systemctl action failed: {e}")
        # Re-raise to let the API handle the HTTP 500
        raise

async def reload_and_restart(server_id: int, unit_name: str, scope: str = 'global'):
    """
    Helper to trigger daemon-reload then restart a unit,
    which is typically done after a file is saved.

    Both steps use allow_failure=True so that a non-zero exit code from
    systemctl (e.g. the unit fails to start after the config change) is
    logged as a warning rather than raising an exception that would mask the
    successful file save and cause the UI to display a contradictory error.
    """
    await systemctl_action(server_id, 'daemon-reload', "", scope=scope, allow_failure=True)
    await systemctl_action(server_id, 'restart', unit_name, scope=scope, allow_failure=True)
