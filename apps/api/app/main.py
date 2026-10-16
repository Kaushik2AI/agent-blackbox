"""FastAPI application factory."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import evaluations, executions, health, ingest, live, replays


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="FlightPath API",
        version="0.1.0",
        description=(
            "FlightPath: health, idempotent event ingestion (M3), read APIs (M4), "
            "evidence-backed findings (M5), sandboxed checkpoint replay (M6) and "
            "original-vs-fork comparison (M7). No auth yet: local development only."
        ),
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(ingest.router)
    app.include_router(executions.router)
    app.include_router(replays.router)
    app.include_router(live.router)
    app.include_router(evaluations.router)
    return app


app = create_app()
