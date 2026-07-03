import asyncio
import logging
import os
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from core.database import init_db
from core.crypto import ensure_master_key
from services.sync_engine import polling_engine_loop
from services.stats_engine import stats_engine_loop
from services.container_events import container_events_cleanup_loop
from services.ssh_manager import pool
from api.routes import router as web_router
from api.routes import _load_session_duration_from_db

_log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, _log_level, logging.INFO))
logger = logging.getLogger("quadlet-manager")

# Background task references for clean shutdown
_background_tasks: list[asyncio.Task] = []

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting QuadletManager backend...")
    
    # 1. Initialize SQLite schema
    await init_db()

    # 2. Ensure a stable encryption key exists before any SSH operations run
    await ensure_master_key()

    # 2b. Hydrate the in-memory session duration from any persisted setting
    await _load_session_duration_from_db()

    # 3. Start the Polling Engine as a background asyncio task
    _background_tasks.append(asyncio.create_task(polling_engine_loop()))

    # 4. Start the Resource Stats Engine as a background asyncio task
    _background_tasks.append(asyncio.create_task(stats_engine_loop()))

    # 5. Start the Container Events cleanup task
    _background_tasks.append(asyncio.create_task(container_events_cleanup_loop()))
    
    yield
    
    logger.info("Shutting down QuadletManager backend...")
    
    # Cancel background tasks first so they stop making new DB connections
    for task in _background_tasks:
        task.cancel()
    # Wait for tasks to finish cancellation
    await asyncio.gather(*_background_tasks, return_exceptions=True)
    _background_tasks.clear()
    
    await pool.close_all()

app = FastAPI(title="QuadletManager Dashboard", lifespan=lifespan)

@app.exception_handler(HTTPException)
async def redirect_on_auth(request: Request, exc: HTTPException):
    """Convert 303 auth-redirect exceptions into actual browser redirects."""
    if exc.status_code == 303 and exc.headers and "Location" in exc.headers:
        return RedirectResponse(url=exc.headers["Location"], status_code=303)
    # For all other HTTPExceptions, return the default JSON response
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )

# Mock static files mount to prevent startup crash if missing
import os
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(web_router)
