from fastapi import APIRouter, Request, Depends, Form, HTTPException, WebSocket
from fastapi.responses import HTMLResponse
import re
import shlex

from database import get_db_connection
from sockets import stream_logs_over_websocket
from ssh_manager import pool
from tree_scanner import fetch_all_quadlets
from systemd_manager import systemctl_action, reload_and_restart
import logging

logger = logging.getLogger("quadlet-manager.routes")
router = APIRouter()

async def get_current_user_role():
    return "editor"

@router.get("/", response_class=HTMLResponse)
async def dashboard_view(request: Request):
    return """
    <html>
    <head>
        <title>QuadletManager Setup</title>
        <script src="https://unpkg.com/htmx.org@1.9.11"></script>
        <script src="https://cdn.tailwindcss.com"></script>
        <link rel="stylesheet" href="/static/style.css">
    </head>
    <body class="bg-gray-900 text-white flex h-screen overflow-hidden">
        <div id="navigator" class="w-1/4 bg-gray-800 border-r border-gray-700 p-4 overflow-y-auto">
            <h2 class="text-xl font-bold mb-4">Servers</h2>
            <div hx-get="/api/servers" hx-trigger="load">Loading servers...</div>
        </div>
        
        <div id="editor-pane" class="w-1/2 flex flex-col border-r border-gray-700">
            <div class="p-4 bg-gray-800 flex justify-between items-center">
                <h2 class="text-xl font-bold">Editor</h2>
                <!-- Buttons injected dynamically when a file is opened -->
                <div id="editor-actions"></div>
            </div>
            <!-- The form that HTMX submits -->
            <form id="save-form" hx-post="/api/save" hx-target="#status-toast" class="hidden">
                <input type="hidden" name="server_id" id="hidden-server-id">
                <input type="hidden" name="file_path" id="hidden-file-path">
                <input type="hidden" name="scope" id="hidden-scope">
                <input type="hidden" name="unit_name" id="hidden-unit-name">
                <textarea name="content" id="hidden-content"></textarea>
            </form>
            <div id="editor-container" class="flex-1 bg-gray-950 p-4 font-mono text-sm" contenteditable="true">
                # Select a file from the navigator...
            </div>
        </div>
        
        <div id="inspector" class="w-1/4 bg-gray-800 p-4">
            <h2 class="text-xl font-bold mb-4">Inspector</h2>
            <div id="status-toast" class="mb-4"></div>
            
            <div class="flex space-x-2 mb-2" id="systemctl-actions">
                <!-- Action buttons loaded dynamically -->
            </div>
            
            <div id="systemd-status" class="bg-black p-2 rounded text-xs font-mono text-green-400 h-64 overflow-y-auto whitespace-pre-wrap">
                Systemd status will appear here...
            </div>
        </div>
        
        <script src="https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs/loader.min.js"></script>
        <script src="/static/main.js"></script>
    </body>
    </html>
    """

@router.get("/api/servers")
async def api_servers():
    async with await get_db_connection() as db:
        async with db.execute("SELECT id, name FROM servers") as cursor:
            servers = await cursor.fetchall()
            
    html = '<ul class="space-y-4">'
    for server in servers:
        html += f'''
        <li>
            <div class="font-bold text-lg mb-1">{server[1]}</div>
            <div class="pl-4 text-sm" hx-get="/api/quadlets/{server[0]}" hx-trigger="load">
                Scanning quadlets...
            </div>
        </li>'''
    
    if not servers:
        html += '<li class="text-gray-500 italic">No servers configured. Db seeded?</li>'
    html += '</ul>'
    return HTMLResponse(html)

@router.get("/api/quadlets/{server_id}")
async def fetch_quadlet_tree(server_id: int):
    try:
        data = await fetch_all_quadlets(server_id)
        
        html = ""
        for scope in ['global', 'user']:
            html += f'<div class="font-semibold text-gray-400 mt-2 uppercase text-xs">{scope} Scope</div>'
            html += '<ul class="space-y-1 mt-1">'
            if not data[scope]:
                html += '<li class="text-gray-500 italic text-xs">No files found</li>'
                
            for file_info in data[scope]:
                # Endpoint to load file into editor
                url = f"/api/file/{server_id}?path={file_info['path']}&scope={scope}&name={file_info['name']}"
                html += f'''
                <li>
                    <button class="text-blue-400 hover:text-blue-300 hover:underline text-left block w-full"
                            hx-get="{url}" hx-target="#editor-pane" hx-swap="outerHTML">
                        📄 {file_info['name']}
                    </button>
                </li>
                '''
            html += '</ul>'
        return HTMLResponse(html)
    except Exception as e:
        logger.error(f"Error fetching quadlets: {e}")
        return HTMLResponse(f"<div class='text-red-500'>Error loading files</div>")

@router.get("/api/file/{server_id}")
async def fetch_file(server_id: int, path: str, scope: str, name: str):
    use_sudo = (scope == 'global')
    cmd = f"cat {shlex.quote(path)}"
    try:
        content = await pool.execute_command(server_id, cmd, use_sudo=use_sudo)
        # Unit name is derived from filename (e.g. 'nginx.container' -> 'nginx.service')
        # Though podman auto-generates .service for .container
        base_name = name.rsplit('.', 1)[0]
        unit_name = f"{base_name}.service"
        
        # We need to swap the editor-pane to re-initialize Monaco with new content,
        # or we can emit an HTMX event to trigger the existing JS.
        # Sending JS directly to update the editor is easier for HTMX:
        safe_content = content.replace('`', '\\`').replace('$', '\\$').replace('<', '\\u003c')
        
        # Load the right panel systemctl status too
        status_url = f"/api/systemctl/status/{server_id}?unit={unit_name}&scope={scope}"
        
        return HTMLResponse(f"""
        <div id="editor-pane" class="w-1/2 flex flex-col border-r border-gray-700">
            <div class="p-4 bg-gray-800 flex justify-between items-center">
                <h2 class="text-xl font-bold">Editor: {name}</h2>
                <div id="editor-actions">
                    <button id="save-btn" class="bg-blue-600 hover:bg-blue-500 px-4 py-2 rounded text-sm font-semibold"
                            onclick="document.getElementById('hidden-content').value = window.editor.getValue(); document.getElementById('save-form').dispatchEvent(new Event('submit', {{cancelable: true, bubbles: true}}));">
                        Save Quadlet
                    </button>
                </div>
            </div>
            <form id="save-form" hx-post="/api/save" hx-target="#status-toast" class="hidden">
                <input type="hidden" name="server_id" value="{server_id}">
                <input type="hidden" name="file_path" value="{path}">
                <input type="hidden" name="scope" value="{scope}">
                <input type="hidden" name="unit_name" value="{unit_name}">
                <textarea name="content" id="hidden-content"></textarea>
            </form>
            <div id="editor-container" class="flex-1 bg-gray-950 p-4 font-mono text-sm"></div>
            
            <!-- Update the Inspector Pane simultaneously using HTMX OOB Swaps -->
            <div id="systemctl-actions" hx-swap-oob="true" class="flex space-x-2 mb-2">
                <button class="bg-green-700 hover:bg-green-600 px-2 py-1 text-xs rounded"
                        hx-post="/api/systemctl/{server_id}?action=start&unit={unit_name}&scope={scope}" hx-target="#systemd-status">Start</button>
                <button class="bg-red-700 hover:bg-red-600 px-2 py-1 text-xs rounded"
                        hx-post="/api/systemctl/{server_id}?action=stop&unit={unit_name}&scope={scope}" hx-target="#systemd-status">Stop</button>
                <button class="bg-yellow-700 hover:bg-yellow-600 px-2 py-1 text-xs rounded"
                        hx-post="/api/systemctl/{server_id}?action=restart&unit={unit_name}&scope={scope}" hx-target="#systemd-status">Restart</button>
            </div>
            
            <div id="systemd-status" hx-swap-oob="true" hx-get="{status_url}" hx-trigger="load" class="bg-black p-2 rounded text-xs font-mono text-green-400 h-64 overflow-y-auto whitespace-pre-wrap">
                Loading status...
            </div>
            
            <script>
                if (window.editor) {{
                    window.editor.setValue(`{safe_content}`);
                }} else {{
                    require(['vs/editor/editor.main'], function() {{
                        window.editor = monaco.editor.create(document.getElementById('editor-container'), {{
                            value: `{safe_content}`,
                            language: 'ini',
                            theme: 'vs-dark',
                            automaticLayout: true
                        }});
                    }});
                }}
            </script>
        </div>
        """)
    except Exception as e:
        logger.error(f"Error fetching file: {e}")
        return HTMLResponse("<div class='text-red-500'>Failed to load file content</div>")

@router.post("/api/save")
async def save_file(
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
    # Write to a temporary file via printf, then move to avoid escaping nightmares
    # But since it's SSH, we can pipe it
    safe_content = shlex.quote(content)
    cmd = f"printf '%s' {safe_content} | "
    if use_sudo:
        cmd += f"sudo tee {shlex.quote(file_path)} > /dev/null"
    else:
        cmd += f"tee {shlex.quote(file_path)} > /dev/null"
        
    try:
        await pool.execute_command(server_id, cmd, use_sudo=False) # Sudo is inside the pipe
        
        # Do daemon-reload and restart
        await reload_and_restart(server_id, unit_name, scope)
        
        # Fetch updated status
        status_output = await systemctl_action(server_id, "status", unit_name, scope)
        
        return HTMLResponse(f"""
        <div class="bg-green-600 p-2 rounded text-sm font-bold toast-enter">Saved & Restarted {unit_name}!</div>
        <div id="systemd-status" hx-swap-oob="true" class="bg-black p-2 rounded text-xs font-mono text-green-400 h-64 overflow-y-auto whitespace-pre-wrap">{status_output}</div>
        """)
    except Exception as e:
        logger.error(f"Save failed: {e}")
        return HTMLResponse(f"<div class='bg-red-600 p-2 rounded text-sm font-bold toast-enter'>Failed to save: {str(e)}</div>")

@router.get("/api/systemctl/status/{server_id}")
async def api_systemctl_status(server_id: int, unit: str, scope: str):
    try:
        output = await systemctl_action(server_id, "status", unit, scope)
        return HTMLResponse(output)
    except Exception as e:
        return HTMLResponse(str(e))

@router.post("/api/systemctl/{server_id}")
async def api_systemctl_post(server_id: int, action: str, unit: str, scope: str, role: str = Depends(get_current_user_role)):
    if role != "editor" and action != "status":
        return HTMLResponse("Permission denied", status_code=403)
        
    try:
        await systemctl_action(server_id, action, unit, scope)
        # Fetch status to show update
        output = await systemctl_action(server_id, "status", unit, scope)
        return HTMLResponse(output)
    except Exception as e:
        return HTMLResponse(f"Action failed: {str(e)}")

@router.websocket("/ws/logs/{server_id}/{unit_name}")
async def websocket_logs(websocket: WebSocket, server_id: int, unit_name: str):
    await stream_logs_over_websocket(websocket, server_id, unit_name)
