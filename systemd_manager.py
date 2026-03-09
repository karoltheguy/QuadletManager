import logging
from ssh_manager import pool
from database import get_db_connection

logger = logging.getLogger("quadlet-manager.systemd")

async def systemctl_action(server_id: int, action: str, unit_name: str, scope: str = 'global'):
    """
    Executes a systemctl action (start, stop, restart, status) on a unit.
    Applies user-level systemctl if scope is 'user', otherwise global.
    """
    allowed_actions = ['start', 'stop', 'restart', 'status', 'daemon-reload']
    if action not in allowed_actions:
        raise ValueError(f"Invalid systemctl action: {action}")
        
    use_sudo = (scope == 'global')
    cmd_prefix = "systemctl"
    if scope == 'user':
        cmd_prefix = "systemctl --user"
        
    cmd = f"{cmd_prefix} {action}"
    if action != 'daemon-reload' and unit_name:
        cmd += f" {unit_name}"

    try:
        logger.info(f"Running '{cmd}' on server_id={server_id} (sudo={use_sudo})")
        return await pool.execute_command(server_id, cmd, use_sudo=use_sudo)
    except Exception as e:
        logger.error(f"Systemctl action failed: {e}")
        # Re-raise to let the API handle the HTTP 500
        raise

async def reload_and_restart(server_id: int, unit_name: str, scope: str = 'global'):
    """
    Helper to trigger daemon-reload then restart a unit,
    which is typically done after a file is saved.
    """
    await systemctl_action(server_id, 'daemon-reload', "", scope=scope)
    await systemctl_action(server_id, 'restart', unit_name, scope=scope)
