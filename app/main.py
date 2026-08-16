from __future__ import annotations

import logging
import threading
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth import verify_api_key
from app.collector import purge_old_messages, run_collector
from app.config import get_settings
from app.database import init_db
from app.routes import aircraft, health, messages, stats

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    init_db(settings.database)

    def _collector():
        health.collector_running = True
        try:
            run_collector()
        finally:
            health.collector_running = False

    threading.Thread(target=_collector, daemon=True, name="collector").start()
    log.info("Collector thread started")

    def _cleanup():
        while True:
            time.sleep(3600)
            deleted = purge_old_messages()
            if deleted:
                log.info("Retention cleanup: removed %d message(s)", deleted)

    threading.Thread(target=_cleanup, daemon=True, name="retention").start()

    yield


def _create_app() -> FastAPI:
    # get_settings() is called here rather than at module scope so that
    # importing app.main in tests does not trigger settings loading before
    # patches are applied.
    settings = get_settings()

    application = FastAPI(
        title="VDL2 API",
        description="REST API for decoded VDL Mode 2 messages collected from dumpvdl2.",
        version="1.0.0",
        lifespan=lifespan,
    )

    if settings.cors_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["GET"],
            allow_headers=["*"],
        )

    PREFIX = "/api/v1"
    application.include_router(messages.router, prefix=PREFIX, tags=["messages"], dependencies=[Depends(verify_api_key)])
    application.include_router(aircraft.router, prefix=PREFIX, tags=["aircraft"], dependencies=[Depends(verify_api_key)])
    application.include_router(stats.router, prefix=PREFIX, tags=["stats"], dependencies=[Depends(verify_api_key)])
    application.include_router(health.router, prefix=PREFIX, tags=["health"], dependencies=[Depends(verify_api_key)])

    return application


app = _create_app()
