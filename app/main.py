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

    log.info(
        "VDL2 API starting — host=%s port=%d db=%s spool=%s retention=%dd",
        settings.api_host,
        settings.api_port,
        settings.database,
        settings.spool,
        settings.retention_days,
    )
    if settings.api_key:
        log.info("Authentication: X-API-Key required")
    else:
        log.warning("Authentication: disabled — set VDL2_API_KEY to require a key")

    if settings.cors_origins:
        log.info("CORS: allowed origins — %s", ", ".join(settings.cors_origins))
    else:
        log.info("CORS: disabled")

    init_db(settings.database)

    stop_event = threading.Event()

    def _collector():
        health.collector_running = True
        try:
            run_collector(stop_event=stop_event)
        finally:
            health.collector_running = False

    collector_thread = threading.Thread(target=_collector, daemon=True, name="collector")
    collector_thread.start()
    log.info("Collector thread started")

    def _cleanup():
        while not stop_event.is_set():
            stop_event.wait(timeout=3600)
            if stop_event.is_set():
                break
            purge_old_messages()

    threading.Thread(target=_cleanup, daemon=True, name="retention").start()
    log.info("Retention cleanup thread started — interval=1h retention=%dd", settings.retention_days)

    yield

    log.info("Shutdown: signalling collector to stop")
    stop_event.set()
    # 10 s is generous for a normal shutdown. During a large catch-up drain
    # (e.g. after a long outage) the collector may be mid-batch and take
    # longer. If the join times out the thread is still running; the daemon
    # flag ensures the OS kills it when the process exits, which is the same
    # outcome as before graceful shutdown was added. The WAL journal protects
    # against DB corruption; the only loss is the checkpoint for the current
    # batch, which will be re-processed on next startup (INSERT OR IGNORE
    # makes that safe).
    collector_thread.join(timeout=10)
    if collector_thread.is_alive():
        log.warning(
            "Collector thread did not stop within 10 s — "
            "process will exit with thread still running (daemon)"
        )
    else:
        log.info("Collector thread stopped cleanly")


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
