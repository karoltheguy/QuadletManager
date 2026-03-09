import os
import logging
from typing import List, Dict
from ssh_manager import pool

logger = logging.getLogger("quadlet-manager.scanner")

GLOBAL_DIR = "/etc/containers/systemd"
USER_DIR = "~/.config/containers/systemd"

async def scan_directory(server_id: int, path: str, use_sudo: bool) -> List[Dict]:
    """Uses SSH to run `find` and lists files in the given directory."""
    
    # We grep for specific known Quadlet extensions.
    cmd = rf"find {path} -type f -maxdepth 1 | grep -E '\.(container|volume|network|pod)$' || true"
    
    try:
        output = await pool.execute_command(server_id, cmd, use_sudo=use_sudo)
        files = output.strip().split('\n')
        
        results = []
        for file_path in files:
            if not file_path:
                continue
            
            file_name = os.path.basename(file_path)
            # Create a logical split for UI
            results.append({
                "path": file_path,
                "name": file_name,
                "scope": "global" if use_sudo else "user"
            })
            
        return results
    except Exception as e:
        logger.error(f"Error scanning {path} on server {server_id}: {e}")
        return []

async def fetch_all_quadlets(server_id: int) -> Dict[str, List[Dict]]:
    """Scans both global and rootless Quadlet scopes"""
    logger.info(f"Scanning server {server_id} for Quadlets...")
    
    # Needs sudo for /etc
    global_files = await scan_directory(server_id, GLOBAL_DIR, use_sudo=True)
    # No sudo for ~
    user_files = await scan_directory(server_id, USER_DIR, use_sudo=False)
    
    return {
        "global": global_files,
        "user": user_files
    }
