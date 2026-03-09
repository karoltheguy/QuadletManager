import asyncio
import logging
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from core.database import init_db
from services.sync_engine import polling_engine_loop
from services.ssh_manager import pool
from api.routes import router as web_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("quadlet-manager")

app = FastAPI(title="QuadletManager Dashboard")

# Mock static files mount to prevent startup crash if missing
import os
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(web_router)

@app.on_event("startup")
async def startup_event():
    logger.info("Starting QuadletManager backend...")
    
    # 1. Initialize SQLite schema
    await init_db()
    
    # 2. Start the Polling Engine as a background asyncio task
    asyncio.create_task(polling_engine_loop())

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutting down QuadletManager backend...")
    await pool.close_all()
