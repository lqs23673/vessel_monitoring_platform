from __future__ import annotations

from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import router, shutdown_realtime, start_camera
from .config import get_settings
from .live_capture import safe_camera_error
from .database import Base, engine
from .jobs import job_manager
from .recording_api import router as recording_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    job_manager.start()
    try:
        if get_settings().live_capture_autostart:
            try:
                await start_camera()
            except Exception as exc:
                # Keep settings and diagnostics accessible if capture cannot start.
                logging.getLogger("vessel.startup").error(
                    "Camera autostart failed: %s", safe_camera_error(exc, get_settings())
                )
        yield
    finally:
        await shutdown_realtime()
        job_manager.stop()


app = FastAPI(title="VesselSight Operations API", version="2.0", docs_url="/api/docs", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(router)
app.include_router(recording_router)


@app.get("/")
def root(): return {"service": "VesselSight Operations API", "version": "2.0"}
