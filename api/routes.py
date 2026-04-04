from fastapi import APIRouter, Request, Depends, Form, File, HTTPException, UploadFile, WebSocket
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse, JSONResponse
from typing import Optional
from fastapi.templating import Jinja2Templates
import hashlib
import re
import shlex
import time

from core.database import get_db_connection
from core.crypto import encrypt_private_key
from api.sockets import stream_logs_over_websocket
from services.ssh_manager import pool
from services.quadlet_parser import validate_quadlet_syntax, QuadletValidationError
from services.tree_scanner import fetch_all_quadlets
from services.systemd_manager import systemctl_action, reload_and_restart
from services.sync_engine import parse_mtime
from core.events_manager import publisher
import logging
from core.config_loader import global_config

from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
import secrets

logger = logging.getLogger("quadlet-manager.routes")
router = APIRouter()
templates = Jinja2Templates(directory="templates")

# ── Session Configuration ─────────────────────────────────
# Secret key for signing session cookies
SESSION_SECRET = secrets.token_hex(32)
SESSION_MAX_AGE = 3600  # 1 hour

serializer = URLSafeTimedSerializer(SESSION_SECRET)

COOKIE_NAME = "qm_session"


def _create_session_cookie(username: str, role: str, is_admin: bool = False) -> str:
    """Create a signed session cookie value."""
    return serializer.dumps({"username": username, "role": role, "is_admin": is_admin})


def _read_session_cookie(cookie_value: str) -> dict | None:
    """Read and validate a signed session cookie. Returns None if invalid."""
    try:
        return serializer.loads(cookie_value, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None


async def _get_session(request: Request) -> dict:
    """Return the full session dict {"username": ..., "role": ...}.
    Raises HTTPException(303) redirect to /login if not authenticated.
    """
    if global_config.dev_auto_login:
        return {"username": "admin", "role": "editor", "is_admin": True}

    cookie = request.cookies.get(COOKIE_NAME)
    if not cookie:
        raise HTTPException(status_code=303, headers={"Location": "/login"})

    session = _read_session_cookie(cookie)
    if not session:
        raise HTTPException(status_code=303, headers={"Location": "/login"})

    return session


async def get_current_user_role(request: Request) -> str:
    """Extract the user role from the session cookie.
    Raises HTTPException(303) redirect to /login if not authenticated.
    Set DEV_AUTO_LOGIN=1 or dev_auto_login: true in config.yaml
    to bypass auth entirely during development.
    """
    session = await _get_session(request)
    return session["role"]


async def get_optional_user_role(request: Request) -> str | None:
    """Same as get_current_user_role but returns None instead of redirecting."""
    if global_config.dev_auto_login:
        return "editor"

    cookie = request.cookies.get(COOKIE_NAME)
    if not cookie:
        return None
    session = _read_session_cookie(cookie)
    if not session:
        return None
    return session["role"]


async def get_current_user_is_admin(request: Request) -> bool:
    """Return True if the current session user has admin privileges."""
    if global_config.dev_auto_login:
        return True
    session = await _get_session(request)
    return bool(session.get("is_admin", False))


async def require_admin(is_admin: bool = Depends(get_current_user_is_admin)) -> None:
    """FastAPI dependency that raises 403 if the current user is not an admin."""
    if not is_admin:
        raise HTTPException(status_code=403, detail="Admin access required.")


# ── Login / Logout ────────────────────────────────────────
@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    # If already logged in, redirect to dashboard
    role = await get_optional_user_role(request)
    if role:
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    async with get_db_connection() as db:
        async with db.execute(
            "SELECT password_hash, role, is_admin FROM users WHERE username = ?",
            (username,)
        ) as cursor:
            row = await cursor.fetchone()

    if not row:
        return templates.TemplateResponse(request, "login.html", {
            "error": "Invalid username or password"
        }, status_code=401)

    stored_hash = row[0]
    role = row[1]
    is_admin = bool(row[2])
    current_hash = hashlib.sha256(password.encode()).hexdigest()

    if not secrets.compare_digest(current_hash, stored_hash):
        return templates.TemplateResponse(request, "login.html", {
            "error": "Invalid username or password"
        }, status_code=401)

    # Credentials valid – set session cookie and redirect to dashboard
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(
        key=COOKIE_NAME,
        value=_create_session_cookie(username, role, is_admin),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(COOKIE_NAME)
    return response


# ── Dashboard ─────────────────────────────────────────────
@router.get("/", response_class=HTMLResponse)
async def dashboard_view(request: Request, role: str = Depends(get_current_user_role)):
    return templates.TemplateResponse(request, "dashboard.html", {
        "user_role": role
    })

@router.get("/api/servers", response_class=HTMLResponse)
async def api_servers(request: Request):
    async with get_db_connection() as db:
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

    quadlet_type = file_path.rsplit('.', 1)[-1].lower()
    if quadlet_type in ('container', 'volume', 'network', 'pod', 'kube'):
        try:
            validate_quadlet_syntax(content, quadlet_type)
        except QuadletValidationError as ve:
            return templates.TemplateResponse(request, "partials/toast.html", {
                "color": "red",
                "message": f"Validation error: {ve}",
                "status_output": None
            })

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
            
            async with get_db_connection() as db:
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
        
    async with get_db_connection() as db:
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
        
    async with get_db_connection() as db:
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
        
        response = templates.TemplateResponse(request, "partials/toast.html", {
            "color": "green",
            "message": f"Created {file_name}!",
            "status_output": None
        })
        response.headers["HX-Trigger"] = "reload-servers"
        return response
    except Exception as e:
        logger.error(f"Failed to create quadlet: {e}")
        return templates.TemplateResponse(request, "partials/toast.html", {
            "color": "red",
            "message": f"Creation Failed: {str(e)}",
            "status_output": None
        })

@router.get("/api/health/history/{server_id}")
async def api_health_history(server_id: int, minutes: int = 60):
    """Return per-container health history for the last N minutes."""
    cutoff = int(time.time()) - minutes * 60
    async with get_db_connection() as db:
        async with db.execute(
            "SELECT container_name, is_running, cpu_pct, mem_pct, recorded_at "
            "FROM container_health_history "
            "WHERE server_id = ? AND recorded_at >= ? "
            "ORDER BY recorded_at ASC",
            (server_id, cutoff),
        ) as cursor:
            rows = await cursor.fetchall()

    containers: dict[str, dict] = {}
    for row in rows:
        name, is_running, cpu, mem, ts = row
        if name not in containers:
            containers[name] = {"container_name": name, "history": []}
        containers[name]["history"].append({
            "ts": ts,
            "is_running": is_running,
            "cpu": cpu,
            "mem": mem,
        })

    return JSONResponse(list(containers.values()))


@router.get("/api/settings/servers", response_class=HTMLResponse)
async def settings_list_servers(request: Request, role: str = Depends(get_current_user_role)):
    async with get_db_connection() as db:
        async with db.execute(
            "SELECT s.id, s.name, s.ip_address, s.ssh_user, k.key_name "
            "FROM servers s LEFT JOIN ssh_keys k ON s.ssh_key_id = k.id "
            "ORDER BY s.name"
        ) as cursor:
            servers = await cursor.fetchall()
    return templates.TemplateResponse(request, "partials/settings_servers.html", {
        "servers": servers,
        "user_role": role,
    })


@router.post("/api/settings/servers", response_class=HTMLResponse)
async def settings_add_server(
    request: Request,
    name: str = Form(...),
    ip_address: str = Form(...),
    ssh_user: str = Form(...),
    key_name: str = Form(...),
    private_key: str = Form(...),
    role: str = Depends(get_current_user_role),
    is_admin: bool = Depends(get_current_user_is_admin),
):
    if not is_admin:
        raise HTTPException(status_code=403, detail="Admin access required.")

    encrypted = encrypt_private_key(private_key)
    async with get_db_connection() as db:
        await db.execute(
            "INSERT OR IGNORE INTO ssh_keys (key_name, encrypted_private_key) VALUES (?, ?)",
            (key_name, encrypted),
        )
        await db.commit()
        async with db.execute("SELECT id FROM ssh_keys WHERE key_name = ?", (key_name,)) as cursor:
            key_row = await cursor.fetchone()
        await db.execute(
            "INSERT INTO servers (name, ip_address, ssh_user, ssh_key_id) VALUES (?, ?, ?, ?)",
            (name, ip_address, ssh_user, key_row[0]),
        )
        await db.commit()

    response = await settings_list_servers(request, role)
    response.headers["HX-Trigger"] = "reload-servers"
    return response


@router.put("/api/settings/servers/{server_id}", response_class=HTMLResponse)
async def settings_update_server(
    request: Request,
    server_id: int,
    name: str = Form(...),
    ip_address: str = Form(...),
    ssh_user: str = Form(...),
    role: str = Depends(get_current_user_role),
    is_admin: bool = Depends(get_current_user_is_admin),
):
    if not is_admin:
        raise HTTPException(status_code=403, detail="Admin access required.")

    async with get_db_connection() as db:
        await db.execute(
            "UPDATE servers SET name = ?, ip_address = ?, ssh_user = ? WHERE id = ?",
            (name, ip_address, ssh_user, server_id),
        )
        await db.commit()

    response = await settings_list_servers(request, role)
    response.headers["HX-Trigger"] = "reload-servers"
    return response


@router.delete("/api/settings/servers/{server_id}", response_class=HTMLResponse)
async def settings_delete_server(
    request: Request,
    server_id: int,
    role: str = Depends(get_current_user_role),
    is_admin: bool = Depends(get_current_user_is_admin),
):
    if not is_admin:
        raise HTTPException(status_code=403, detail="Admin access required.")

    # Close cached SSH connection if present
    pool.connections.pop(server_id, None)

    async with get_db_connection() as db:
        async with db.execute("SELECT ssh_key_id FROM servers WHERE id = ?", (server_id,)) as cursor:
            row = await cursor.fetchone()
        await db.execute("DELETE FROM servers WHERE id = ?", (server_id,))
        await db.commit()

        # Clean up the SSH key if no other server references it
        if row and row[0]:
            async with db.execute(
                "SELECT COUNT(*) FROM servers WHERE ssh_key_id = ?", (row[0],)
            ) as cursor:
                count_row = await cursor.fetchone()
            if count_row[0] == 0:
                await db.execute("DELETE FROM ssh_keys WHERE id = ?", (row[0],))
                await db.commit()

    response = await settings_list_servers(request, role)
    response.headers["HX-Trigger"] = "reload-servers"
    return response


# ── User Management ───────────────────────────────────────
@router.get("/api/settings/users", response_class=HTMLResponse)
async def settings_list_users(
    request: Request,
    role: str = Depends(get_current_user_role),
    is_admin: bool = Depends(get_current_user_is_admin),
):
    if not is_admin:
        return HTMLResponse("<p class='text-muted'>Permission denied.</p>", status_code=403)

    session = await _get_session(request)
    async with get_db_connection() as db:
        async with db.execute(
            "SELECT id, username, role FROM users ORDER BY username"
        ) as cursor:
            users = await cursor.fetchall()
    return templates.TemplateResponse(request, "partials/settings_users.html", {
        "users": users,
        "current_username": session["username"],
    })


@router.post("/api/settings/users", response_class=HTMLResponse)
async def settings_add_user(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    user_role: str = Form(...),
    role: str = Depends(get_current_user_role),
    is_admin: bool = Depends(get_current_user_is_admin),
):
    if not is_admin:
        raise HTTPException(status_code=403, detail="Admin access required.")

    if user_role not in ("viewer", "editor"):
        raise HTTPException(status_code=400, detail="Invalid role.")

    password_hash = hashlib.sha256(password.encode()).hexdigest()
    async with get_db_connection() as db:
        try:
            await db.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                (username, password_hash, user_role),
            )
            await db.commit()
        except Exception:
            return HTMLResponse(
                "<p class='text-danger'>Username already exists.</p>",
                status_code=409,
            )

    return await settings_list_users(request, role, is_admin=True)


@router.put("/api/settings/users/{user_id}", response_class=HTMLResponse)
async def settings_update_user_role(
    request: Request,
    user_id: int,
    user_role: str = Form(...),
    role: str = Depends(get_current_user_role),
    is_admin: bool = Depends(get_current_user_is_admin),
):
    if not is_admin:
        raise HTTPException(status_code=403, detail="Admin access required.")

    if user_role not in ("viewer", "editor"):
        raise HTTPException(status_code=400, detail="Invalid role.")

    session = await _get_session(request)
    async with get_db_connection() as db:
        # Prevent demoting yourself
        async with db.execute("SELECT username FROM users WHERE id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
        if row and row[0] == session["username"]:
            return HTMLResponse(
                "<p class='text-danger'>Cannot change your own role.</p>",
                status_code=400,
            )

        await db.execute(
            "UPDATE users SET role = ? WHERE id = ?",
            (user_role, user_id),
        )
        await db.commit()

    return await settings_list_users(request, role, is_admin=True)


@router.delete("/api/settings/users/{user_id}", response_class=HTMLResponse)
async def settings_delete_user(
    request: Request,
    user_id: int,
    role: str = Depends(get_current_user_role),
    is_admin: bool = Depends(get_current_user_is_admin),
):
    if not is_admin:
        raise HTTPException(status_code=403, detail="Admin access required.")

    session = await _get_session(request)
    async with get_db_connection() as db:
        # Prevent self-deletion
        async with db.execute("SELECT username FROM users WHERE id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
        if row and row[0] == session["username"]:
            return HTMLResponse(
                "<p class='text-danger'>Cannot delete your own account.</p>",
                status_code=400,
            )

        await db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        await db.commit()

    return await settings_list_users(request, role, is_admin=True)


# ── SSH Key Management ────────────────────────────────────
@router.get("/api/keys", response_class=HTMLResponse)
async def api_list_keys(
    request: Request,
    is_admin: bool = Depends(get_current_user_is_admin),
):
    if not is_admin:
        return HTMLResponse("<p class='text-muted'>Permission denied.</p>", status_code=403)

    async with get_db_connection() as db:
        async with db.execute("SELECT id, key_name FROM ssh_keys ORDER BY key_name") as cursor:
            keys = await cursor.fetchall()

    return templates.TemplateResponse(request, "partials/settings_keys.html", {
        "keys": keys,
    })


@router.post("/api/keys", response_class=HTMLResponse)
async def api_add_key(
    request: Request,
    key_name: str = Form(...),
    private_key: str = Form(default=""),
    key_file: Optional[UploadFile] = File(default=None),
    is_admin: bool = Depends(get_current_user_is_admin),
):
    if not is_admin:
        raise HTTPException(status_code=403, detail="Admin access required.")

    if key_file and key_file.filename:
        raw = await key_file.read()
        key_content = raw.decode("utf-8")
    elif private_key.strip():
        key_content = private_key
    else:
        raise HTTPException(status_code=400, detail="No key content provided.")

    encrypted = encrypt_private_key(key_content)
    async with get_db_connection() as db:
        await db.execute(
            "INSERT OR IGNORE INTO ssh_keys (key_name, encrypted_private_key) VALUES (?, ?)",
            (key_name, encrypted),
        )
        await db.commit()

    return await api_list_keys(request, is_admin=True)


@router.delete("/api/keys/{key_id}", response_class=HTMLResponse)
async def api_delete_key(
    request: Request,
    key_id: int,
    is_admin: bool = Depends(get_current_user_is_admin),
):
    if not is_admin:
        raise HTTPException(status_code=403, detail="Admin access required.")

    async with get_db_connection() as db:
        async with db.execute(
            "SELECT COUNT(*) FROM servers WHERE ssh_key_id = ?", (key_id,)
        ) as cursor:
            row = await cursor.fetchone()
        if row and row[0] > 0:
            raise HTTPException(
                status_code=409,
                detail="Key is still in use by one or more servers.",
            )
        await db.execute("DELETE FROM ssh_keys WHERE id = ?", (key_id,))
        await db.commit()

    return await api_list_keys(request, is_admin=True)


@router.websocket("/ws/logs/{server_id}/{unit_name}")
async def websocket_logs(websocket: WebSocket, server_id: int, unit_name: str, scope: str = "user"):
    await stream_logs_over_websocket(websocket, server_id, unit_name, scope)
