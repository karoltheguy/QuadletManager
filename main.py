import asyncio
import logging
import os

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from api.routes import (
    AuthRedirect,
    _load_log_level_from_db,
    _load_session_duration_from_db,
    ensure_session_secret,
)
from api.routes import router as web_router
from core.crypto import ensure_master_key
from core.database import init_db
from core.version import get_version
from services.container_events import container_events_cleanup_loop
from services.ssh_manager import pool
from services.stats_engine import stats_engine_loop
from services.sync_engine import polling_engine_loop

_log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, _log_level, logging.INFO))
logger = logging.getLogger("quadlet-manager")

# Background task references for clean shutdown
_background_tasks: list[asyncio.Task] = []

from contextlib import asynccontextmanager


class _PollingAccessLogFilter(logging.Filter):
    """Drops uvicorn access-log records for the polling endpoint."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if not isinstance(args, tuple) or len(args) != 5:
            return True
        full_path = args[2]
        return full_path.split("?", 1)[0] != "/api/overview"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Starting QuadletManager backend... (version {get_version()})")

    # 0. Filter noisy polling requests out of the uvicorn access log.
    # Must happen here (not at module import time) because uvicorn configures
    # its own "uvicorn.access" logger before the app's lifespan hook runs.
    logging.getLogger("uvicorn.access").addFilter(_PollingAccessLogFilter())

    # 1. Initialize SQLite schema
    await init_db()

    # 2. Ensure a stable encryption key exists before any SSH operations run
    await ensure_master_key()

    # 2b. Hydrate the in-memory session duration from any persisted setting
    await _load_session_duration_from_db()

    # 2b-2. Hydrate the in-memory log level from any persisted setting
    await _load_log_level_from_db()

    # 2c. Ensure a stable session secret exists before any cookies are issued
    await ensure_session_secret()

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

@app.exception_handler(AuthRedirect)
async def redirect_on_auth(request: Request, exc: AuthRedirect):
    """Send an unauthenticated caller to the login page.

    Every other HTTPException falls through to FastAPI's built-in handler,
    which is what the deleted status-code branch here was reimplementing.
    """
    return RedirectResponse(url=exc.location, status_code=exc.status_code)

# Mock static files mount to prevent startup crash if missing
app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(web_router)
