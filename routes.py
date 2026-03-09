from fastapi import APIRouter, Request, Depends, HTTPException, WebSocket
from fastapi.responses import HTMLResponse
from database import get_db_connection
from sockets import stream_logs_over_websocket
from ssh_manager import pool

router = APIRouter()

# Dependency mock for current user role
async def get_current_user_role():
    # In a real app, this parses a session cookie or JWT token
    # For now, assuming Editor role for rapid development
    return "editor"

@router.get("/", response_class=HTMLResponse)
async def dashboard_view(request: Request):
    # In reality this should render Jinja2 templates, 
    # but for simplicity we return boilerplate for the HTMX UI
    return """
    <html>
    <head>
        <title>QuadletManager Setup</title>
        <script src="https://unpkg.com/htmx.org@1.9.11"></script>
        <script src="https://cdn.tailwindcss.com"></script>
        <link rel="stylesheet" href="/static/style.css">
    </head>
    <body class="bg-gray-900 text-white flex h-screen overflow-hidden">
        <!-- 3-Pane Layout Placeholder -->
        <div id="navigator" class="w-1/4 bg-gray-800 border-r border-gray-700 p-4 overflow-y-auto">
            <h2 class="text-xl font-bold mb-4">Servers</h2>
            <div hx-get="/api/servers" hx-trigger="load">Loading servers...</div>
        </div>
        <div id="editor" class="w-1/2 flex flex-col border-r border-gray-700">
            <div class="p-4 bg-gray-800 flex justify-between">
                <h2 class="text-xl font-bold">Editor</h2>
                <button class="bg-blue-600 hover:bg-blue-500 px-4 py-2 rounded text-sm font-semibold"
                        hx-post="/api/save" hx-include="#editor-container" hx-target="#status-toast">Save Quadlet</button>
            </div>
            <div id="editor-container" class="flex-1 bg-gray-950 p-4 font-mono text-sm" contenteditable="true">
                # Select a file from the navigator...
            </div>
        </div>
        <div id="inspector" class="w-1/4 bg-gray-800 p-4">
            <h2 class="text-xl font-bold mb-4">Inspector</h2>
            <div id="status-toast" class="mb-4"></div>
            <div id="systemd-status" class="bg-black p-2 rounded text-xs font-mono text-green-400 h-64 overflow-y-auto">
                Systemd status will appear here...
            </div>
        </div>
    </body>
    </html>
    """

@router.get("/api/servers")
async def api_servers():
    async with await get_db_connection() as db:
        async with db.execute("SELECT id, name FROM servers") as cursor:
            servers = await cursor.fetchall()
            
    html = '<ul class="space-y-2">'
    for server in servers:
        html += f'<li><button class="text-blue-400 hover:underline" hx-get="/api/quadlets/{server[0]}" hx-target="#editor-container">{server[1]}</button></li>'
    if not servers:
        html += '<li class="text-gray-500 italic">No servers configured. Db seeded?</li>'
    html += '</ul>'
    return HTMLResponse(html)

@router.post("/api/save")
async def save_file(request: Request, role: str = Depends(get_current_user_role)):
    if role != "editor":
        raise HTTPException(status_code=403, detail="Viewer role cannot save files.")
    
    # Needs to extract actual editor text from payload
    # For now, it's mocked collision avoidance DB update
    return HTMLResponse('<div class="bg-green-600 p-2 rounded text-sm font-bold">Successfully saved file!</div>')

@router.websocket("/ws/logs/{server_id}/{unit_name}")
async def websocket_logs(websocket: WebSocket, server_id: int, unit_name: str):
    await stream_logs_over_websocket(websocket, server_id, unit_name)
