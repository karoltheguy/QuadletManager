from fastapi import APIRouter, Request, Depends, Form, File, HTTPException, UploadFile, WebSocket
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse, JSONResponse, Response
from typing import Optional
from fastapi.templating import Jinja2Templates
import asyncio
import hashlib
import html
import os
from argon2 import PasswordHasher, exceptions
import json
import re
import secrets
import shlex
import time

import aiosqlite
from core.database import get_db_connection
from core.crypto import encrypt_private_key
from api.sockets import stream_logs_over_websocket, exec_terminal_over_websocket
from services.ssh_manager import pool, SSHCommandError, SSHTimeoutError
from services.quadlet_parser import validate_quadlet_syntax, QuadletValidationError
from services.remote_fs import is_global_scope, quadlet_dir_for_scope, write_remote_file
from services.tree_scanner import fetch_all_quadlets
from services.systemd_manager import systemctl_action, reload_and_restart
from services.quadlet_validator import validate_remote
import services.sync_engine as sync_engine
from services.sync_engine import parse_mtime
from core.events_manager import publisher
from services.container_events import record_container_event, get_container_activity
from services.quadlet_naming import base_name_of, unit_name_for, quadlet_type_of
import logging
from core.config_loader import global_config
from core.version import get_version

from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
import secrets

logger = logging.getLogger("quadlet-manager.routes")
router = APIRouter()
templates = Jinja2Templates(directory="templates")

STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")


def _asset_version(filename: str) -> int:
    """Return the on-disk mtime (as an int) of a static asset, for cache-busting."""
    return int(os.path.getmtime(os.path.join(STATIC_DIR, filename)))



def _log_error_ref(prefix: str, exc: Exception) -> str:
    """Log exc with a short random correlation id and return the id so the
    same reference can be shown to the user without leaking exception detail."""
    ref = secrets.token_hex(3)
    logger.error(f"{prefix} (ref: {ref}): {exc}")
    return ref


def _toast(request: Request, color: str, message: str, status_output=None) -> HTMLResponse:
    """Render the shared toast partial. Callers may set HX-Trigger on the result."""
    return templates.TemplateResponse(request, "partials/toast.html", {
        "color": color,
        "message": message,
        "status_output": status_output,
    })

# ── Session Configuration ─────────────────────────────────
# Secret key for signing session cookies
SESSION_SECRET = secrets.token_hex(32)

SESSION_DURATION_SETTING_KEY = "session_duration_seconds"
SESSION_DURATION_CHOICES = (3600, 86400, 604800, 2592000, 7776000, 31536000)  # 1h/1d/1wk/1mo/3mo/1yr
SESSION_DURATION_LABELS = (
    (3600, "1 hour"),
    (86400, "1 day"),
    (604800, "1 week"),
    (2592000, "1 month"),
    (7776000, "3 months"),
    (31536000, "1 year"),
)

# Mutable at runtime via PUT /api/settings/session-duration; seeded from config.yaml's
# session_timeout (or its 3600 default) until a value is persisted to the settings table.
_session_duration_seconds = global_config.session_timeout

LOG_LEVEL_SETTING_KEY = "log_level"
LOG_LEVEL_CHOICES = ("DEBUG", "INFO", "WARNING")

# Mutable at runtime via PUT /api/settings/log-level; seeded the same way main.py seeds
# its own startup logging.basicConfig level, until a value is persisted to the settings table.
_log_level = os.getenv("LOG_LEVEL", "INFO").upper()

serializer = URLSafeTimedSerializer(SESSION_SECRET)


async def ensure_session_secret() -> None:
    """Ensure a stable session secret is available before any cookies are issued.

    If QUADLET_SESSION_SECRET is set, it is used directly (and nothing is persisted
    to the database). Otherwise a dev secret is loaded from (or persisted to) the
    `settings` table so signed session cookies survive application restarts. Call
    this once at startup after init_db().
    """
    global SESSION_SECRET, serializer

    env_secret = os.getenv("QUADLET_SESSION_SECRET")
    if env_secret:
        SESSION_SECRET = env_secret
        serializer = URLSafeTimedSerializer(SESSION_SECRET)
        return

    candidate = secrets.token_hex(32)
    async with get_db_connection() as db:
        insert_cursor = await db.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES ('session_secret', ?)",
            (candidate,),
        )
        await db.commit()

        async with db.execute(
            "SELECT value FROM settings WHERE key = 'session_secret'"
        ) as select_cursor:
            row = await select_cursor.fetchone()
        resolved = row[0]

        if insert_cursor.rowcount == 0:
            logger.warning(
                "QUADLET_SESSION_SECRET not set; loaded persisted dev session secret "
                "from database. Set QUADLET_SESSION_SECRET to a stable value for production."
            )
        else:
            logger.warning(
                "QUADLET_SESSION_SECRET not set; generated and persisted a dev session "
                "secret to the database. This is NOT secure for production. Set "
                "QUADLET_SESSION_SECRET to a stable value."
            )

    SESSION_SECRET = resolved
    serializer = URLSafeTimedSerializer(SESSION_SECRET)


COOKIE_NAME = "qm_session"


def _create_session_cookie(username: str, role: str, is_admin: bool = False, must_change_password: bool = False) -> str:
    """Create a signed session cookie value."""
    return serializer.dumps({
        "username": username,
        "role": role,
        "is_admin": is_admin,
        "must_change_password": must_change_password,
    })


def _read_session_cookie(cookie_value: str) -> dict | None:
    """Read and validate a signed session cookie. Returns None if invalid."""
    try:
        return serializer.loads(cookie_value, max_age=_session_duration_seconds)
    except (BadSignature, SignatureExpired):
        return None


async def _load_session_duration_from_db() -> None:
    """Hydrate the in-memory session duration from the persisted setting, if any."""
    global _session_duration_seconds
    async with get_db_connection() as db:
        async with db.execute(
            "SELECT value FROM settings WHERE key = ?", (SESSION_DURATION_SETTING_KEY,)
        ) as cursor:
            row = await cursor.fetchone()
    if row:
        _session_duration_seconds = int(row[0])


async def _persist_session_duration(seconds: int) -> None:
    """Persist the session duration to the settings table and update the in-memory value."""
    global _session_duration_seconds
    async with get_db_connection() as db:
        async with db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (SESSION_DURATION_SETTING_KEY, str(seconds)),
        ):
            pass
        await db.commit()
    _session_duration_seconds = seconds


async def _load_log_level_from_db() -> None:
    """Hydrate the in-memory log level from the persisted setting, if any."""
    global _log_level
    async with get_db_connection() as db:
        async with db.execute(
            "SELECT value FROM settings WHERE key = ?", (LOG_LEVEL_SETTING_KEY,)
        ) as cursor:
            row = await cursor.fetchone()
    if row:
        stored_value = row[0]
        if stored_value not in LOG_LEVEL_CHOICES:
            logger.warning(
                "Ignoring invalid stored log level %r", stored_value
            )
            return
        _log_level = stored_value
        logging.getLogger("quadlet-manager").setLevel(_log_level)


async def _persist_log_level(level: str) -> None:
    """Persist the log level to the settings table, update the in-memory value, and apply it live."""
    global _log_level
    async with get_db_connection() as db:
        async with db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (LOG_LEVEL_SETTING_KEY, level),
        ):
            pass
        await db.commit()
    _log_level = level
    logging.getLogger("quadlet-manager").setLevel(level)


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

    if (
        session.get("must_change_password")
        and request.url.path != "/change-password"
        and request.url.path != "/logout"
    ):
        raise HTTPException(status_code=303, headers={"Location": "/change-password"})

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


async def get_current_username(request: Request) -> str:
    """Extract the username from the session cookie."""
    session = await _get_session(request)
    return session["username"]


async def require_admin(is_admin: bool = Depends(get_current_user_is_admin)) -> None:
    """Verify that the current user has admin privileges, raising 403 if not."""
    if not is_admin:
        raise HTTPException(status_code=403, detail="Admin access required.")


async def get_current_user_id(username: str = Depends(get_current_username)) -> int:
    """Resolve the current session username to a numeric user id (404 if missing)."""
    async with get_db_connection() as db:
        row = await (await db.execute(
            "SELECT id FROM users WHERE username=?", (username,)
        )).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return row[0]


async def load_active_theme(user_id: int) -> dict:
    """Return mode_pref + parsed light/dark override dicts for the user's active theme."""
    async with get_db_connection() as db:
        row = await (await db.execute(
            "SELECT mode_preference, light_overrides_json, dark_overrides_json "
            "FROM user_themes WHERE user_id=? AND is_active=1",
            (user_id,),
        )).fetchone()
    if not row:
        return {"mode_pref": "auto", "light": {}, "dark": {}}
    return {
        "mode_pref": row[0],
        "light": json.loads(row[1] or "{}"),
        "dark": json.loads(row[2] or "{}"),
    }


async def _ensure_default_theme(user_id: int) -> None:
    """Lazily insert a single Default theme row for a user who has none yet."""
    async with get_db_connection() as db:
        existing = await (await db.execute(
            "SELECT id FROM user_themes WHERE user_id=?", (user_id,)
        )).fetchone()
        if existing:
            return
        now = int(time.time())
        await db.execute(
            """INSERT INTO user_themes
               (user_id, theme_name, mode_preference,
                light_overrides_json, dark_overrides_json,
                is_active, created_at, updated_at)
               VALUES (?, 'Default', 'auto', '{}', '{}', 1, ?, ?)""",
            (user_id, now, now),
        )
        await db.commit()


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
            "SELECT password_hash, role, is_admin, must_change_password FROM users WHERE username = ?",
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
    must_change_password = bool(row[3])

    ph = PasswordHasher()
    credentials_valid = False

    try:
        ph.verify(stored_hash, password)
        credentials_valid = True
    except (exceptions.VerifyMismatchError, exceptions.InvalidHashError):
        pass

    if not credentials_valid:
        return templates.TemplateResponse(request, "login.html", {
            "error": "Invalid username or password"
        }, status_code=401)

    # Credentials valid – set session cookie and redirect to dashboard
    # (or to the forced password-change page, if flagged)
    redirect_url = "/change-password" if must_change_password else "/"
    response = RedirectResponse(url=redirect_url, status_code=303)
    response.set_cookie(
        key=COOKIE_NAME,
        value=_create_session_cookie(username, role, is_admin, must_change_password),
        max_age=_session_duration_seconds,
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(COOKIE_NAME)
    return response


@router.get("/change-password", response_class=HTMLResponse)
async def change_password_page(request: Request):
    await _get_session(request)
    return templates.TemplateResponse(request, "change_password.html", {"error": None})


@router.post("/change-password", response_class=HTMLResponse)
async def change_password_submit(
    request: Request,
    new_password: str = Form(...),
    confirm_password: str = Form(...),
):
    session = await _get_session(request)

    if not new_password or new_password != confirm_password:
        return templates.TemplateResponse(request, "change_password.html", {
            "error": "Passwords do not match"
        }, status_code=400)

    username = session["username"]
    role = session["role"]
    is_admin = bool(session.get("is_admin", False))

    new_hash = PasswordHasher().hash(new_password)
    async with get_db_connection() as db:
        await db.execute(
            "UPDATE users SET password_hash = ?, must_change_password = 0 WHERE username = ?",
            (new_hash, username),
        )
        await db.commit()

    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(
        key=COOKIE_NAME,
        value=_create_session_cookie(username, role, is_admin, must_change_password=False),
        max_age=_session_duration_seconds,
        httponly=True,
        samesite="lax",
    )
    return response


# ── Dashboard ─────────────────────────────────────────────
@router.get("/", response_class=HTMLResponse)
async def dashboard_view(
    request: Request,
    role: str = Depends(get_current_user_role),
    is_admin: bool = Depends(get_current_user_is_admin),
    username: str = Depends(get_current_username),
    user_id: int = Depends(get_current_user_id),
):
    await _ensure_default_theme(user_id)
    active_theme = await load_active_theme(user_id)
    return templates.TemplateResponse(request, "dashboard.html", {
        "user_role": role,
        "is_admin": is_admin,
        "username": username,
        "active_theme_mode_pref": active_theme["mode_pref"],
        "active_theme_light": active_theme["light"],
        "active_theme_dark": active_theme["dark"],
        "app_version": get_version(),
        "static_main_js_version": _asset_version("main.js"),
        "static_style_css_version": _asset_version("style.css"),
    })

@router.get("/api/servers", response_class=HTMLResponse)
async def api_servers(request: Request, role: str = Depends(get_current_user_role)):
    async with get_db_connection() as db:
        async with db.execute("SELECT id, name FROM servers ORDER BY position") as cursor:
            servers = await cursor.fetchall()

    return templates.TemplateResponse(request, "partials/servers_list.html", {
        "servers": servers,
        "user_role": role,
    })

@router.get("/api/overview", response_class=HTMLResponse)
async def api_overview(request: Request, role: str = Depends(get_current_user_role)):
    """Return the fleet-level overview partial for HTMX polling."""
    async with get_db_connection() as db:
        async with db.execute("SELECT id, name FROM servers") as cursor:
            server_rows = await cursor.fetchall()

        servers = []
        for server_id, server_name in server_rows:
            async with db.execute(
                """
                SELECT h.container_name, MAX(h.is_running), MAX(h.health_status)
                FROM container_health_history h
                INNER JOIN (
                    SELECT container_name, MAX(recorded_at) AS max_ts
                    FROM container_health_history
                    WHERE server_id = ?
                    GROUP BY container_name
                ) latest ON h.container_name = latest.container_name
                        AND h.recorded_at = latest.max_ts
                        AND h.server_id = ?
                GROUP BY h.container_name
                """,
                (server_id, server_id),
            ) as cursor:
                container_rows = await cursor.fetchall()

            seen_names: set[str] = set()
            containers = []
            for name, is_running, health_status in container_rows:
                if name not in seen_names:
                    seen_names.add(name)
                    containers.append({
                        "name": name,
                        "status": "running" if is_running else "stopped",
                        "health": health_status or "",
                    })
            running = sum(1 for c in containers if c["status"] == "running")
            stopped = sum(1 for c in containers if c["status"] == "stopped")
            servers.append({
                "name": server_name,
                "containers": containers,
                "running": running,
                "stopped": stopped,
            })

    total_servers = len(servers)
    total_running = sum(s["running"] for s in servers)
    total_stopped = sum(s["stopped"] for s in servers)
    total_unreported = sum(1 for s in servers if not s["containers"])

    return templates.TemplateResponse(request, "partials/overview.html", {
        "servers": servers,
        "total_servers": total_servers,
        "total_running": total_running,
        "total_stopped": total_stopped,
        "total_unreported": total_unreported,
    })


@router.get("/api/quadlets/{server_id}", response_class=HTMLResponse)
async def fetch_quadlet_tree(request: Request, server_id: int, role: str = Depends(get_current_user_role)):
    try:
        async with get_db_connection() as db:
            async with db.execute(
                "SELECT scope_filter FROM servers WHERE id = ?", (server_id,)
            ) as cursor:
                row = await cursor.fetchone()
        scope_filter = row[0] if row else "both"
        data = await fetch_all_quadlets(server_id, scope_filter=scope_filter)
        return templates.TemplateResponse(request, "partials/quadlet_tree.html", {
            "server_id": server_id,
            "data": data
        })
    except Exception as e:
        logger.error(f"Error fetching quadlets: {e}")
        return HTMLResponse("<div class='text-red-500 text-xs'>Error loading files</div>")

@router.get("/api/file/{server_id}", response_class=HTMLResponse)
async def fetch_file(request: Request, server_id: int, path: str, scope: str, name: str, role: str = Depends(get_current_user_role)):
    use_sudo = is_global_scope(scope)
    cmd = f"cat {shlex.quote(path)}"
    try:
        content = await pool.execute_command(server_id, cmd, use_sudo=use_sudo)
        base_name = base_name_of(name)
        unit_name = unit_name_for(name)
        quadlet_type = quadlet_type_of(name)
        pod_name = base_name if quadlet_type == 'pod' else None
        
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
            "user_role": role,
            "quadlet_type": quadlet_type,
            "pod_name": pod_name
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

    quadlet_type = quadlet_type_of(file_path)
    if quadlet_type in ('container', 'volume', 'network', 'pod', 'kube'):
        try:
            validate_quadlet_syntax(content, quadlet_type)
        except QuadletValidationError as ve:
            return _toast(request, "red", f"Validation error: {ve}")

    use_sudo = is_global_scope(scope)
    try:
        await write_remote_file(server_id, file_path, content, use_sudo=use_sudo)

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

        # Restart in the background, *after* responding. A save can target the unit
        # that is currently running QuadletManager itself; awaiting the restart here
        # would kill this request (and the process serving it) before the response
        # - including the HX-Trigger the client relies on to clear the dirty indicator -
        # ever reaches the browser.
        async def _restart_in_background():
            try:
                await reload_and_restart(server_id, unit_name, scope)
            except Exception as restart_err:
                logger.error(f"Background restart of {unit_name} failed: {restart_err}")

        asyncio.create_task(_restart_in_background())

        response = _toast(request, "green", f"Saved! Restarting {unit_name}...")
        response.headers["HX-Trigger"] = "quadlet-saved"
        return response
    except Exception as e:
        ref = _log_error_ref("Save failed", e)
        return _toast(request, "red", f"Failed to save (ref: {ref})")

@router.post("/api/validate/{server_id}")
async def validate_quadlet(
    server_id: int,
    file_path: str = Form(...),
    scope: str = Form(...),
    content: str = Form(...),
    role: str = Depends(get_current_user_role)
):
    file_name = file_path.split("/")[-1]
    try:
        result = await validate_remote(server_id, content, file_name, scope)
        return JSONResponse(result)
    except (SSHCommandError, SSHTimeoutError) as e:
        ref = _log_error_ref("Validation failed", e)
        return JSONResponse({"error": f"Validation failed (ref: {ref})"}, status_code=502)

@router.get("/api/systemctl/status/{server_id}", response_class=HTMLResponse)
async def api_systemctl_status(server_id: int, unit: str, scope: str, role: str = Depends(get_current_user_role)):
    try:
        output = await systemctl_action(server_id, "status", unit, scope)
        return HTMLResponse(output)
    except Exception as e:
        ref = _log_error_ref("Error fetching systemctl status", e)
        return HTMLResponse(f"Failed to get status (ref: {ref})")

@router.post("/api/systemctl/{server_id}", response_class=HTMLResponse)
async def api_systemctl_post(
    request: Request,
    server_id: int,
    action: str,
    unit: str,
    scope: str,
    role: str = Depends(get_current_user_role)
):
    if role != "editor" and action != "status":
        return HTMLResponse("Permission denied", status_code=403)

    try:
        await systemctl_action(server_id, action, unit, scope)
        output = await systemctl_action(server_id, "status", unit, scope)

        # Record event for start/stop/restart actions
        if action in ("start", "stop", "restart"):
            session = await _get_session(request)
            username = session["username"]
            stem = base_name_of(unit)
            await record_container_event(server_id, stem, action, triggered_by=username)

        return HTMLResponse(output)
    except Exception as e:
        logger.error(f"Systemctl action '{action}' failed: {e}")
        return HTMLResponse("Action failed")

@router.post("/api/pod-action/{server_id}", response_class=HTMLResponse)
async def api_pod_action(
    request: Request,
    server_id: int,
    action: str,
    pod_name: str,
    scope: str,
    role: str = Depends(get_current_user_role)
):
    if role != "editor":
        return HTMLResponse("Permission denied", status_code=403)

    if action not in ("start", "stop", "restart"):
        return HTMLResponse(f"Invalid pod action: {html.escape(action)}", status_code=400)

    use_sudo = is_global_scope(scope)
    safe_pod_name = shlex.quote(pod_name)
    cmd = f"podman pod {action} {safe_pod_name}"

    try:
        output = await pool.execute_command(server_id, cmd, use_sudo=use_sudo)

        if action in ("start", "stop", "restart"):
            session = await _get_session(request)
            username = session["username"]
            await record_container_event(server_id, pod_name, action, triggered_by=username)

        return HTMLResponse(output)
    except Exception as e:
        logger.error(f"Pod action '{action}' failed: {e}")
        return HTMLResponse("Pod action failed")

@router.get("/api/events")
async def sse_events(request: Request, role: str = Depends(get_current_user_role)):
    return StreamingResponse(publisher.event_generator(request), media_type="text/event-stream")

@router.get("/api/activity/{server_id}")
async def get_activity(server_id: int, container: str, limit: int = 10, role: str = Depends(get_current_user_role)):
    """Fetch container activity events."""
    try:
        limit = min(limit, 100)
        events = await get_container_activity(server_id, container, limit=limit)
        return {"events": events}
    except Exception as e:
        logger.error(f"Failed to fetch activity: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch activity")

@router.get("/api/modal/new", response_class=HTMLResponse)
async def new_file_modal(request: Request, server_id: int | None = None, role: str = Depends(get_current_user_role)):
    if role != "editor":
        return HTMLResponse("<div class='bg-red-600 p-2 rounded'>Permission denied</div>", status_code=403)

    async with get_db_connection() as db:
        async with db.execute("SELECT id, name FROM servers") as cursor:
            servers = await cursor.fetchall()

    return templates.TemplateResponse(request, "partials/modal_new.html", {
        "servers": servers,
        "preselected_server_id": server_id,
    })

@router.post("/api/create", response_class=HTMLResponse)
async def create_new_quadlet(
    request: Request,
    server_id: int = Form(...),
    scope: str = Form(...),
    quadlet_type: str = Form(..., alias="type"),
    name: str = Form(...),
    role: str = Depends(get_current_user_role)
):
    if role != "editor":
        raise HTTPException(status_code=403, detail="Viewer role cannot create files.")
        
    async with get_db_connection() as db:
        async with db.execute("SELECT content FROM templates WHERE type = ? LIMIT 1", (quadlet_type,)) as cursor:
            row = await cursor.fetchone()
            content = row[0] if row else f"[{quadlet_type.capitalize()}]\n"
            
    file_name = f"{name}.{quadlet_type}"
    use_sudo = is_global_scope(scope)
    try:
        target_dir = await quadlet_dir_for_scope(server_id, scope)
        file_path = f"{target_dir}/{file_name}"
        await pool.execute_command(server_id, f"mkdir -p {shlex.quote(target_dir)}", use_sudo=use_sudo)
        await write_remote_file(server_id, file_path, content, use_sudo=use_sudo)

        response = _toast(request, "green", f"Created {file_name}!")
        response.headers["HX-Trigger"] = "reload-servers"
        return response
    except Exception as e:
        ref = _log_error_ref("Failed to create quadlet", e)
        return _toast(request, "red", f"Creation Failed (ref: {ref})")

@router.get("/api/health/history/{server_id}")
async def api_health_history(server_id: int, minutes: int = 60, role: str = Depends(get_current_user_role)):
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


@router.get("/api/poll-health")
async def api_poll_health(role: str = Depends(get_current_user_role)):
    """Return the poll health tracker's current snapshot."""
    return JSONResponse(sync_engine.health_tracker.snapshot())


@router.get("/api/settings/servers", response_class=HTMLResponse)
async def settings_list_servers(
    request: Request,
    role: str = Depends(get_current_user_role),
    is_admin: bool = Depends(get_current_user_is_admin),
):
    async with get_db_connection() as db:
        async with db.execute(
            "SELECT s.id, s.name, s.ip_address, s.ssh_user, k.key_name, s.scope_filter "
            "FROM servers s LEFT JOIN ssh_keys k ON s.ssh_key_id = k.id "
            "ORDER BY s.position"
        ) as cursor:
            servers = await cursor.fetchall()
    return templates.TemplateResponse(request, "partials/settings_servers.html", {
        "servers": servers,
        "user_role": role,
        "is_admin": is_admin,
    })


VALID_SCOPE_FILTERS = {"user", "global", "both"}

@router.post("/api/settings/servers", response_class=HTMLResponse)
async def settings_add_server(
    request: Request,
    name: str = Form(...),
    ip_address: str = Form(...),
    ssh_user: str = Form(...),
    ssh_key_id: int = Form(...),
    scope_filter: str = Form("both"),
    role: str = Depends(get_current_user_role),
    is_admin: bool = Depends(get_current_user_is_admin),
):
    if not is_admin:
        raise HTTPException(status_code=403, detail="Admin access required.")
    if scope_filter not in VALID_SCOPE_FILTERS:
        raise HTTPException(status_code=422, detail="scope_filter must be 'user', 'global', or 'both'.")

    async with get_db_connection() as db:
        async with db.execute("SELECT id FROM ssh_keys WHERE id = ?", (ssh_key_id,)) as cursor:
            key_row = await cursor.fetchone()
        if not key_row:
            raise HTTPException(status_code=400, detail="Selected SSH key does not exist.")
        async with db.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM servers") as cur:
            next_pos = (await cur.fetchone())[0]
        await db.execute(
            "INSERT INTO servers (name, ip_address, ssh_user, ssh_key_id, scope_filter, position) VALUES (?, ?, ?, ?, ?, ?)",
            (name, ip_address, ssh_user, ssh_key_id, scope_filter, next_pos),
        )
        await db.commit()

    response = await settings_list_servers(request, role, is_admin=True)
    response.headers["HX-Trigger"] = "reload-servers"
    return response


@router.put("/api/settings/servers/{server_id}", response_class=HTMLResponse)
async def settings_update_server(
    request: Request,
    server_id: int,
    name: str = Form(...),
    ip_address: str = Form(...),
    ssh_user: str = Form(...),
    scope_filter: str = Form("both"),
    role: str = Depends(get_current_user_role),
    is_admin: bool = Depends(get_current_user_is_admin),
):
    if not is_admin:
        raise HTTPException(status_code=403, detail="Admin access required.")
    if scope_filter not in VALID_SCOPE_FILTERS:
        raise HTTPException(status_code=422, detail="scope_filter must be 'user', 'global', or 'both'.")

    async with get_db_connection() as db:
        await db.execute(
            "UPDATE servers SET name = ?, ip_address = ?, ssh_user = ?, scope_filter = ? WHERE id = ?",
            (name, ip_address, ssh_user, scope_filter, server_id),
        )
        await db.commit()

    response = await settings_list_servers(request, role, is_admin=True)
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

    response = await settings_list_servers(request, role, is_admin=True)
    response.headers["HX-Trigger"] = "reload-servers"
    return response


@router.post("/api/settings/servers/{server_id}/repin-host-key", response_class=HTMLResponse)
async def settings_repin_server_host_key(
    request: Request,
    server_id: int,
    role: str = Depends(get_current_user_role),
    is_admin: bool = Depends(get_current_user_is_admin),
):
    if not is_admin:
        raise HTTPException(status_code=403, detail="Admin access required.")

    # Drop the cached SSH connection so the next connect performs a fresh
    # handshake against whatever key the server presents.
    conn = pool.connections.pop(server_id, None)
    if conn:
        try:
            conn.close()
        except Exception as close_exc:
            logger.debug(f"Failed to close stale connection for server {server_id}: {close_exc}")

    async with get_db_connection() as db:
        await db.execute("UPDATE servers SET host_key = NULL WHERE id = ?", (server_id,))
        await db.commit()

    response = await settings_list_servers(request, role, is_admin=True)
    response.headers["HX-Trigger"] = "reload-servers"
    return response


@router.patch("/api/settings/servers/reorder", response_class=HTMLResponse)
async def settings_reorder_servers(
    request: Request,
    role: str = Depends(get_current_user_role),
    is_admin: bool = Depends(get_current_user_is_admin),
):
    if not is_admin:
        raise HTTPException(status_code=403, detail="Admin access required.")

    body = await request.json()
    order = body.get("order", [])
    if not isinstance(order, list) or not all(isinstance(i, int) for i in order):
        raise HTTPException(status_code=422, detail="'order' must be a list of integer server IDs.")

    async with get_db_connection() as db:
        async with db.execute("SELECT id FROM servers") as cursor:
            existing_ids = {row[0] for row in await cursor.fetchall()}

    if set(order) != existing_ids or len(order) != len(existing_ids):
        raise HTTPException(status_code=422, detail="'order' must contain every server ID exactly once.")

    async with get_db_connection() as db:
        for position, server_id in enumerate(order):
            await db.execute("UPDATE servers SET position = ? WHERE id = ?", (position, server_id))
        await db.commit()

    response = await settings_list_servers(request, role, is_admin=True)
    response.headers["HX-Trigger"] = "reload-servers"
    return response


# ── Admin Settings ─────────────────────────────────────────
@router.get("/api/settings/session-duration", response_class=HTMLResponse)
async def settings_get_session_duration(
    request: Request,
    is_admin: bool = Depends(get_current_user_is_admin),
):
    if not is_admin:
        return HTMLResponse("<p class='text-muted'>Permission denied.</p>", status_code=403)

    return templates.TemplateResponse(request, "partials/settings_admin.html", {
        "current_seconds": _session_duration_seconds,
        "duration_choices": SESSION_DURATION_LABELS,
        "current_log_level": _log_level,
        "log_level_choices": LOG_LEVEL_CHOICES,
        "saved": False,
    })


@router.put("/api/settings/session-duration", response_class=HTMLResponse)
async def settings_update_session_duration(
    request: Request,
    session_duration_seconds: int = Form(...),
    is_admin: bool = Depends(get_current_user_is_admin),
):
    if not is_admin:
        raise HTTPException(status_code=403, detail="Admin access required.")

    if session_duration_seconds not in SESSION_DURATION_CHOICES:
        raise HTTPException(status_code=400, detail="Invalid session duration.")

    await _persist_session_duration(session_duration_seconds)
    return templates.TemplateResponse(request, "partials/settings_admin.html", {
        "current_seconds": _session_duration_seconds,
        "duration_choices": SESSION_DURATION_LABELS,
        "current_log_level": _log_level,
        "log_level_choices": LOG_LEVEL_CHOICES,
        "saved": True,
    })


@router.get("/api/settings/log-level", response_class=HTMLResponse)
async def settings_get_log_level(
    request: Request,
    is_admin: bool = Depends(get_current_user_is_admin),
):
    if not is_admin:
        return HTMLResponse("<p class='text-muted'>Permission denied.</p>", status_code=403)

    return templates.TemplateResponse(request, "partials/settings_admin.html", {
        "current_seconds": _session_duration_seconds,
        "duration_choices": SESSION_DURATION_LABELS,
        "current_log_level": _log_level,
        "log_level_choices": LOG_LEVEL_CHOICES,
        "saved": False,
    })


@router.put("/api/settings/log-level", response_class=HTMLResponse)
async def settings_update_log_level(
    request: Request,
    log_level: str = Form(...),
    is_admin: bool = Depends(get_current_user_is_admin),
):
    if not is_admin:
        raise HTTPException(status_code=403, detail="Admin access required.")

    if log_level not in LOG_LEVEL_CHOICES:
        raise HTTPException(status_code=400, detail="Invalid log level.")

    await _persist_log_level(log_level)
    return templates.TemplateResponse(request, "partials/settings_admin.html", {
        "current_seconds": _session_duration_seconds,
        "duration_choices": SESSION_DURATION_LABELS,
        "current_log_level": _log_level,
        "log_level_choices": LOG_LEVEL_CHOICES,
        "saved": True,
    })


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
            "SELECT id, username, role, is_admin FROM users ORDER BY username"
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
    new_is_admin: bool = Form(False),
    role: str = Depends(get_current_user_role),
    is_admin: bool = Depends(get_current_user_is_admin),
):
    if not is_admin:
        raise HTTPException(status_code=403, detail="Admin access required.")

    if user_role not in ("viewer", "editor"):
        raise HTTPException(status_code=400, detail="Invalid role.")

    password_hash = PasswordHasher().hash(password)
    async with get_db_connection() as db:
        try:
            await db.execute(
                "INSERT INTO users (username, password_hash, role, is_admin) VALUES (?, ?, ?, ?)",
                (username, password_hash, user_role, int(new_is_admin)),
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

    if row:
        message = f"Role for '{row[0]}' set to {user_role}"
    else:
        message = "Role updated"

    response = await settings_list_users(request, role, is_admin=True)
    response.headers["HX-Trigger"] = json.dumps({"user-updated": {"message": message}})
    return response


@router.put("/api/settings/users/{user_id}/admin", response_class=HTMLResponse)
async def settings_toggle_admin(
    request: Request,
    user_id: int,
    is_admin_target: bool = Form(...),
    role: str = Depends(get_current_user_role),
    is_admin: bool = Depends(get_current_user_is_admin),
):
    if not is_admin:
        raise HTTPException(status_code=403, detail="Admin access required.")

    session = await _get_session(request)
    async with get_db_connection() as db:
        async with db.execute("SELECT username FROM users WHERE id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
        if row and row[0] == session["username"]:
            return HTMLResponse(
                "<p class='text-danger'>Cannot change your own admin status.</p>",
                status_code=400,
            )

        await db.execute(
            "UPDATE users SET is_admin = ? WHERE id = ?",
            (int(is_admin_target), user_id),
        )
        await db.commit()

    if row:
        if is_admin_target:
            message = f"Admin granted to '{row[0]}'"
        else:
            message = f"Admin revoked from '{row[0]}'"
    else:
        message = "Admin status updated"

    response = await settings_list_users(request, role, is_admin=True)
    response.headers["HX-Trigger"] = json.dumps({"user-updated": {"message": message}})
    return response


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


# ── Theme Settings ────────────────────────────────────────

# Ordered list of customizable theme color keys; the allowlist and the
# template context are both derived from this single source of truth.
THEME_COLOR_KEYS = (
    "bg_base", "bg_surface", "text_primary", "text_muted",
    "brand_primary", "success", "danger", "border_color",
)
THEME_COLOR_ALLOWLIST = frozenset(THEME_COLOR_KEYS)
_HEX_COLOR_RE = re.compile(r'^#[0-9a-fA-F]{6}$')


_DEFAULT_COLORS_DARK = {
    "bg_base": "#1c1f24", "bg_surface": "#22262d", "text_primary": "#e8ecf0",
    "text_muted": "#8b9199", "brand_primary": "#14b8a6", "success": "#10b981",
    "danger": "#ef4444", "border_color": "#2e333b",
}
_DEFAULT_COLORS_LIGHT = {
    "bg_base": "#e8ecf0", "bg_surface": "#eef1f5", "text_primary": "#1c1f24",
    "text_muted": "#6b7280", "brand_primary": "#0d9488", "success": "#059669",
    "danger": "#dc2626", "border_color": "#d3d8e0",
}


async def _require_owned_theme(db, theme_id: int, user_id: int):
    """Return the (id, is_active) row of a theme owned by the user, or raise 404."""
    row = await (await db.execute(
        "SELECT id, is_active FROM user_themes WHERE id=? AND user_id=?", (theme_id, user_id)
    )).fetchone()
    if not row:
        raise HTTPException(status_code=404)
    return row


async def _settings_themes_response(request: Request, user_id: int) -> HTMLResponse:
    async with get_db_connection() as db:
        rows = await (await db.execute(
            "SELECT id, theme_name, mode_preference, light_overrides_json, dark_overrides_json, is_active "
            "FROM user_themes WHERE user_id=? ORDER BY id",
            (user_id,),
        )).fetchall()

    themes = []
    active_theme = None
    for row in rows:
        tid, name, mode_pref, light_json, dark_json, is_active = row
        light = json.loads(light_json or "{}")
        dark = json.loads(dark_json or "{}")
        t = {
            "id": tid, "name": name, "mode_preference": mode_pref,
            "light": light, "dark": dark, "is_active": bool(is_active),
        }
        themes.append(t)
        if is_active:
            active_theme = t

    return templates.TemplateResponse(
        request, "partials/settings_themes.html", {
            "themes": themes,
            "active_theme": active_theme,
            "default_light": _DEFAULT_COLORS_LIGHT,
            "default_dark": _DEFAULT_COLORS_DARK,
            "allowlist": list(THEME_COLOR_KEYS),
        }
    )


@router.get("/api/settings/themes", response_class=HTMLResponse)
async def settings_list_themes(request: Request, user_id: int = Depends(get_current_user_id)):
    await _ensure_default_theme(user_id)
    return await _settings_themes_response(request, user_id)


@router.post("/api/settings/themes", response_class=HTMLResponse)
async def settings_create_theme(
    request: Request,
    theme_name: str = Form(...),
    copy_from: Optional[int] = Form(default=None),
    user_id: int = Depends(get_current_user_id),
):
    light_json = "{}"
    dark_json = "{}"
    if copy_from is not None:
        async with get_db_connection() as db:
            row = await (await db.execute(
                "SELECT light_overrides_json, dark_overrides_json FROM user_themes WHERE id=? AND user_id=?",
                (copy_from, user_id),
            )).fetchone()
        if row:
            light_json, dark_json = row[0], row[1]

    now = int(time.time())
    try:
        async with get_db_connection() as db:
            await db.execute(
                """INSERT INTO user_themes
                   (user_id, theme_name, mode_preference, light_overrides_json, dark_overrides_json,
                    is_active, created_at, updated_at)
                   VALUES (?, ?, 'auto', ?, ?, 0, ?, ?)""",
                (user_id, theme_name, light_json, dark_json, now, now),
            )
            await db.commit()
    except aiosqlite.IntegrityError:
        raise HTTPException(status_code=409, detail=f"Theme name '{theme_name}' already exists.")

    return await _settings_themes_response(request, user_id)


@router.put("/api/settings/themes/{theme_id}", response_class=HTMLResponse)
async def settings_update_theme(
    request: Request,
    theme_id: int,
    theme_name: Optional[str] = Form(default=None),
    mode_preference: Optional[str] = Form(default=None),
    user_id: int = Depends(get_current_user_id),
):
    if mode_preference is not None and mode_preference not in ("auto", "light", "dark"):
        raise HTTPException(status_code=422, detail="mode_preference must be 'auto', 'light', or 'dark'.")

    async with get_db_connection() as db:
        await _require_owned_theme(db, theme_id, user_id)

        updates, params = [], []
        if theme_name is not None:
            updates.append("theme_name=?")
            params.append(theme_name)
        if mode_preference is not None:
            updates.append("mode_preference=?")
            params.append(mode_preference)
        if updates:
            updates.append("updated_at=?")
            params.extend([int(time.time()), theme_id, user_id])
            try:
                await db.execute(
                    f"UPDATE user_themes SET {', '.join(updates)} WHERE id=? AND user_id=?", params
                )
                await db.commit()
            except aiosqlite.IntegrityError:
                raise HTTPException(status_code=409, detail=f"Theme name '{theme_name}' already exists.")

    return await _settings_themes_response(request, user_id)


@router.put("/api/settings/themes/{theme_id}/colors", response_class=HTMLResponse)
async def settings_update_theme_colors(
    request: Request,
    theme_id: int,
    user_id: int = Depends(get_current_user_id),
):
    form = await request.form()
    mode = form.get("mode", "light")
    if mode not in ("light", "dark"):
        raise HTTPException(status_code=422, detail="mode must be 'light' or 'dark'.")

    async with get_db_connection() as db:
        await _require_owned_theme(db, theme_id, user_id)

        overrides, invalid = {}, []
        for key, val in form.items():
            if key == "mode":
                continue
            if key not in THEME_COLOR_ALLOWLIST:
                continue
            if not _HEX_COLOR_RE.match(str(val)):
                invalid.append(key)
            else:
                overrides[key] = val

        if invalid:
            raise HTTPException(status_code=422, detail=f"Invalid hex color for: {', '.join(invalid)}")

        col = "light_overrides_json" if mode == "light" else "dark_overrides_json"
        await db.execute(
            f"UPDATE user_themes SET {col}=?, updated_at=? WHERE id=? AND user_id=?",
            (json.dumps(overrides), int(time.time()), theme_id, user_id),
        )
        await db.commit()

    response = await _settings_themes_response(request, user_id)
    response.headers["HX-Trigger"] = "theme-updated"
    return response


@router.post("/api/settings/themes/{theme_id}/activate", response_class=HTMLResponse)
async def settings_activate_theme(
    request: Request,
    theme_id: int,
    user_id: int = Depends(get_current_user_id),
):
    async with get_db_connection() as db:
        await _require_owned_theme(db, theme_id, user_id)
        await db.execute("UPDATE user_themes SET is_active=0 WHERE user_id=?", (user_id,))
        await db.execute(
            "UPDATE user_themes SET is_active=1 WHERE id=? AND user_id=?", (theme_id, user_id)
        )
        await db.commit()

    response = await _settings_themes_response(request, user_id)
    response.headers["HX-Trigger"] = "theme-updated"
    return response


@router.post("/api/settings/themes/{theme_id}/reset", response_class=HTMLResponse)
async def settings_reset_theme(
    request: Request,
    theme_id: int,
    mode: str = "both",
    user_id: int = Depends(get_current_user_id),
):
    if mode not in ("light", "dark", "both"):
        raise HTTPException(status_code=422, detail="mode must be 'light', 'dark', or 'both'.")

    async with get_db_connection() as db:
        await _require_owned_theme(db, theme_id, user_id)

        now = int(time.time())
        if mode == "light":
            await db.execute(
                "UPDATE user_themes SET light_overrides_json='{}', updated_at=? WHERE id=? AND user_id=?",
                (now, theme_id, user_id),
            )
        elif mode == "dark":
            await db.execute(
                "UPDATE user_themes SET dark_overrides_json='{}', updated_at=? WHERE id=? AND user_id=?",
                (now, theme_id, user_id),
            )
        else:
            await db.execute(
                "UPDATE user_themes SET light_overrides_json='{}', dark_overrides_json='{}', "
                "updated_at=? WHERE id=? AND user_id=?",
                (now, theme_id, user_id),
            )
        await db.commit()

    return await _settings_themes_response(request, user_id)


@router.delete("/api/settings/themes/{theme_id}", response_class=HTMLResponse)
async def settings_delete_theme(
    request: Request,
    theme_id: int,
    user_id: int = Depends(get_current_user_id),
):
    async with get_db_connection() as db:
        row = await _require_owned_theme(db, theme_id, user_id)
        if row[1]:
            raise HTTPException(status_code=400, detail="Cannot delete the active theme.")
        await db.execute("DELETE FROM user_themes WHERE id=? AND user_id=?", (theme_id, user_id))
        await db.commit()

    return await _settings_themes_response(request, user_id)


@router.get("/api/settings/themes/active.css")
async def settings_active_css(user_id: int = Depends(get_current_user_id)):
    async with get_db_connection() as db:
        row = await (await db.execute(
            "SELECT light_overrides_json, dark_overrides_json FROM user_themes "
            "WHERE user_id=? AND is_active=1",
            (user_id,),
        )).fetchone()

    css = ""
    if row:
        light = json.loads(row[0] or "{}")
        dark = json.loads(row[1] or "{}")
        if light:
            vars_css = " ".join(f"--{k.replace('_', '-')}: {v};" for k, v in light.items())
            css += f':root[data-theme="light"] {{ {vars_css} }}\n'
        if dark:
            vars_css = " ".join(f"--{k.replace('_', '-')}: {v};" for k, v in dark.items())
            css += f':root[data-theme="dark"] {{ {vars_css} }}\n'

    return Response(content=css, media_type="text/css")


# ── SSH Key Management ────────────────────────────────────
@router.get("/api/keys/options", response_class=HTMLResponse)
async def api_keys_options(request: Request, role: str = Depends(get_current_user_role)):
    """Return <option> elements for SSH key dropdown."""
    async with get_db_connection() as db:
        async with db.execute("SELECT id, key_name FROM ssh_keys ORDER BY key_name") as cursor:
            keys = await cursor.fetchall()
    if not keys:
        return HTMLResponse('<option value="">No keys available</option>')
    options = '<option value="">Select a key...</option>'
    for k in keys:
        options += f'<option value="{k[0]}">{k[1]}</option>'
    return HTMLResponse(options)


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

    response = await api_list_keys(request, is_admin=True)
    response.headers["HX-Trigger"] = "key-added"
    return response


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


@router.delete("/api/files", response_class=HTMLResponse)
async def delete_file(
    request: Request,
    server_id: int,
    path: str,
    scope: str,
    role: str = Depends(get_current_user_role)
):
    if role != "editor":
        raise HTTPException(status_code=403, detail="Viewer role cannot delete files.")

    use_sudo = is_global_scope(scope)
    cmd = f"sudo rm -f {shlex.quote(path)}" if use_sudo else f"rm -f {shlex.quote(path)}"

    try:
        await pool.execute_command(server_id, cmd, use_sudo=False)

        async with get_db_connection() as db:
            await db.execute(
                "DELETE FROM quadlets WHERE server_id = ? AND file_path = ?",
                (server_id, path)
            )
            await db.commit()

        file_name = path.split("/")[-1]
        response = _toast(request, "green", f"Deleted {file_name}!")
        response.headers["HX-Trigger"] = "reload-servers"
        return response
    except Exception as e:
        ref = _log_error_ref("Delete failed", e)
        return _toast(request, "red", f"Failed to delete (ref: {ref})")


async def _authenticate_websocket(websocket: WebSocket) -> dict | None:
    """Validate the session cookie sent on a WebSocket upgrade.

    Returns the session dict on success, or None if unauthenticated.
    Honors dev_auto_login the same way the HTTP dependency does.
    """
    if global_config.dev_auto_login:
        return {"username": "admin", "role": "editor", "is_admin": True}
    cookie = websocket.cookies.get(COOKIE_NAME)
    if not cookie:
        return None
    return _read_session_cookie(cookie)


@router.websocket("/ws/logs/{server_id}/{unit_name}")
async def websocket_logs(websocket: WebSocket, server_id: int, unit_name: str, scope: str = "user", since: str = None):
    session = await _authenticate_websocket(websocket)
    if session is None:
        logger.warning("Rejected unauthenticated /ws/logs connection")
        await websocket.close(code=4401)
        return
    await stream_logs_over_websocket(websocket, server_id, unit_name, scope, since=since)


@router.websocket("/ws/exec/{server_id}/{container_name}")
async def websocket_exec(websocket: WebSocket, server_id: int, container_name: str, scope: str = "user", cmd: str = "bash"):
    session = await _authenticate_websocket(websocket)
    if session is None:
        logger.warning("Rejected unauthenticated /ws/exec connection")
        await websocket.close(code=4401)
        return
    await exec_terminal_over_websocket(websocket, server_id, container_name, scope, cmd)
