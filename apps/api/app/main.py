"""FastAPI application factory."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import executions, health, ingest


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Agent BlackBox API",
        version="0.1.0",
        description=(
            "Agent BlackBox: health, idempotent event ingestion (M3) and read APIs for the "
            "execution inspector (M4). No replay yet. No auth yet: local development only."
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
    return app


app = create_app()
