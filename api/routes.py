from fastapi import APIRouter, Request, Depends, Form, HTTPException, WebSocket
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
import hashlib
import re
import shlex

from core.database import get_db_connection
from api.sockets import stream_logs_over_websocket
from services.ssh_manager import pool
from services.tree_scanner import fetch_all_quadlets
from services.systemd_manager import systemctl_action, reload_and_restart
from services.sync_engine import parse_mtime
from core.events_manager import publisher
import logging

logger = logging.getLogger("quadlet-manager.routes")
router = APIRouter()
templates = Jinja2Templates(directory="templates")

from fastapi.security import HTTPBasic, HTTPBasicCredentials
import secrets
import hashlib

security = HTTPBasic()

async def get_current_user_role(credentials: HTTPBasicCredentials = Depends(security)):
    async with await get_db_connection() as db:
        async with db.execute(
            "SELECT password_hash, role FROM users WHERE username = ?",
            (credentials.username,)
        ) as cursor:
            row = await cursor.fetchone()
            
            if not row:
                raise HTTPException(
                    status_code=401,
                    detail="Incorrect username or password",
                    headers={"WWW-Authenticate": "Basic"},
                )
            
            stored_hash = row[0]
            role = row[1]
            current_hash = hashlib.sha256(credentials.password.encode()).hexdigest()
            
            if not secrets.compare_digest(current_hash, stored_hash):
                raise HTTPException(
                    status_code=401,
                    detail="Incorrect username or password",
                    headers={"WWW-Authenticate": "Basic"},
                )
            
            return role

@router.get("/", response_class=HTMLResponse)
async def dashboard_view(request: Request, role: str = Depends(get_current_user_role)):
    return templates.TemplateResponse(request, "dashboard.html", {
        "user_role": role
    })

@router.get("/api/servers", response_class=HTMLResponse)
async def api_servers(request: Request):
    async with await get_db_connection() as db:
        async with db.execute("SELECT id, name FROM servers") as cursor:
            servers = await cursor.fetchall()
            
    return templates.TemplateResponse(request, "partials/servers_list.html", {
        "servers": servers
    })

@router.get("/api/quadlets/{server_id}", response_class=HTMLResponse)
async def fetch_quadlet_tree(request: Request, server_id: int):
    try:
        data = await fetch_all_quadlets(server_id)
        return templates.TemplateResponse(request, "partials/quadlet_tree.html", {
            "server_id": server_id,
            "data": data
        })
    except Exception as e:
        logger.error(f"Error fetching quadlets: {e}")
        return HTMLResponse(f"<div class='text-red-500 text-xs'>Error loading files</div>")

@router.get("/api/file/{server_id}", response_class=HTMLResponse)
async def fetch_file(request: Request, server_id: int, path: str, scope: str, name: str, role: str = Depends(get_current_user_role)):
    use_sudo = (scope == 'global')
    cmd = f"cat {shlex.quote(path)}"
    try:
        content = await pool.execute_command(server_id, cmd, use_sudo=use_sudo)
        base_name = name.rsplit('.', 1)[0]
        unit_name = f"{base_name}.service"
        
        safe_content = content.replace('`', '\\`').replace('$', '\\$').replace('<', '\\u003c')
        status_url = f"/api/systemctl/status/{server_id}?unit={unit_name}&scope={scope}"
        
        return templates.TemplateResponse(request, "partials/editor_pane.html", {
            "server_id": server_id,
            "name": name,
            "path": path,
            "scope": scope,
            "unit_name": unit_name,
            "safe_content": safe_content,
            "status_url": status_url,
            "user_role": role
        })
    except Exception as e:
        logger.error(f"Error fetching file: {e}")
        return HTMLResponse("<div class='text-red-500 p-4'>Failed to load file content</div>")

@router.post("/api/save", response_class=HTMLResponse)
async def save_file(
    request: Request,
    server_id: int = Form(...),
    file_path: str = Form(...),
    scope: str = Form(...),
    unit_name: str = Form(...),
    content: str = Form(...),
    role: str = Depends(get_current_user_role)
):
    if role != "editor":
        raise HTTPException(status_code=403, detail="Viewer role cannot save files.")
    
    use_sudo = (scope == 'global')
    safe_content = shlex.quote(content)
    cmd = f"printf '%s' {safe_content} | "
    if use_sudo:
        cmd += f"sudo tee {shlex.quote(file_path)} > /dev/null"
    else:
        cmd += f"tee {shlex.quote(file_path)} > /dev/null"
        
    try:
        await pool.execute_command(server_id, cmd, use_sudo=False)
        await reload_and_restart(server_id, unit_name, scope)
        status_output = await systemctl_action(server_id, "status", unit_name, scope)
        
        # ── Collision Avoidance ──
        # Immediately update the DB with the new mtime so the sync poller
        # doesn't flag our own save as an "external modification."
        try:
            stat_cmd = f"stat -c %Y {shlex.quote(file_path)}"
            mtime_str = await pool.execute_command(server_id, stat_cmd, use_sudo=use_sudo)
            new_mtime = await parse_mtime(mtime_str)
            content_hash = hashlib.sha256(content.encode()).hexdigest()
            
            async with await get_db_connection() as db:
                await db.execute(
                    "UPDATE quadlets SET last_known_mtime = ?, last_content_hash = ? "
                    "WHERE server_id = ? AND file_path = ?",
                    (new_mtime, content_hash, server_id, file_path)
                )
                await db.commit()
        except Exception as ca_err:
            # Non-fatal: the save succeeded, collision avoidance is best-effort
            logger.warning(f"Collision avoidance update failed (save was OK): {ca_err}")
        
        return templates.TemplateResponse(request, "partials/toast.html", {
            "color": "green",
            "message": f"Saved & Restarted {unit_name}!",
            "status_output": status_output
        })
    except Exception as e:
        logger.error(f"Save failed: {e}")
        return templates.TemplateResponse(request, "partials/toast.html", {
            "color": "red",
            "message": f"Failed to save: {str(e)}",
            "status_output": None
        })

@router.get("/api/systemctl/status/{server_id}", response_class=HTMLResponse)
async def api_systemctl_status(server_id: int, unit: str, scope: str):
    try:
        output = await systemctl_action(server_id, "status", unit, scope)
        return HTMLResponse(output)
    except Exception as e:
        return HTMLResponse(str(e))

@router.post("/api/systemctl/{server_id}", response_class=HTMLResponse)
async def api_systemctl_post(server_id: int, action: str, unit: str, scope: str, role: str = Depends(get_current_user_role)):
    if role != "editor" and action != "status":
        return HTMLResponse("Permission denied", status_code=403)
        
    try:
        await systemctl_action(server_id, action, unit, scope)
        output = await systemctl_action(server_id, "status", unit, scope)
        return HTMLResponse(output)
    except Exception as e:
        return HTMLResponse(f"Action failed: {str(e)}")

@router.get("/api/events")
async def sse_events(request: Request):
    return StreamingResponse(publisher.event_generator(request), media_type="text/event-stream")

@router.get("/api/modal/new", response_class=HTMLResponse)
async def new_file_modal(request: Request, role: str = Depends(get_current_user_role)):
    if role != "editor":
        return HTMLResponse("<div class='bg-red-600 p-2 rounded'>Permission denied</div>", status_code=403)
        
    async with await get_db_connection() as db:
        async with db.execute("SELECT id, name FROM servers") as cursor:
            servers = await cursor.fetchall()
            
    return templates.TemplateResponse(request, "partials/modal_new.html", {
        "servers": servers
    })

@router.post("/api/create", response_class=HTMLResponse)
async def create_new_quadlet(
    request: Request,
    server_id: int = Form(...),
    scope: str = Form(...),
    type: str = Form(...),
    name: str = Form(...),
    role: str = Depends(get_current_user_role)
):
    if role != "editor":
        raise HTTPException(status_code=403, detail="Viewer role cannot create files.")
        
    async with await get_db_connection() as db:
        async with db.execute("SELECT content FROM templates WHERE type = ? LIMIT 1", (type,)) as cursor:
            row = await cursor.fetchone()
            content = row[0] if row else f"[{type.capitalize()}]\n"
            
    file_name = f"{name}.{type}"
    target_dir = "/etc/containers/systemd" if scope == "global" else "~/.config/containers/systemd"
    file_path = f"{target_dir}/{file_name}"
    
    use_sudo = (scope == "global")
    safe_content = shlex.quote(content)
    cmd = f"printf '%s' {safe_content} | "
    cmd += (f"sudo tee {shlex.quote(file_path)} > /dev/null" if use_sudo else f"tee {shlex.quote(file_path)} > /dev/null")
    
    try:
        await pool.execute_command(server_id, f"mkdir -p {target_dir}", use_sudo=use_sudo)
        await pool.execute_command(server_id, cmd, use_sudo=False)
        
        return templates.TemplateResponse(request, "partials/toast.html", {
            "color": "green",
            "message": f"Created {file_name}! (Refresh Server to see)",
            "status_output": None
        })
    except Exception as e:
        logger.error(f"Failed to create quadlet: {e}")
        return templates.TemplateResponse(request, "partials/toast.html", {
            "color": "red",
            "message": f"Creation Failed: {str(e)}",
            "status_output": None
        })

@router.websocket("/ws/logs/{server_id}/{unit_name}")
async def websocket_logs(websocket: WebSocket, server_id: int, unit_name: str):
    await stream_logs_over_websocket(websocket, server_id, unit_name)
