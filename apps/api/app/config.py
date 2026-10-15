"""Typed configuration. All values come from environment variables (or a .env file).

Nothing secret has a default: if DATABASE_URL or REDIS_URL is missing the app fails fast
at startup instead of silently connecting somewhere unexpected.
"""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Repo root: apps/api/app/config.py -> parents[3]
REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = "development"
    database_url: str = Field(..., description="SQLAlchemy URL, postgresql+psycopg://...")
    redis_url: str = Field(..., description="redis://:password@127.0.0.1:port/0")
    rq_queue_name: str = "blackbox-default"
    # Origins allowed to call the API directly from a browser. The web app normally
    # talks to the API through the Next.js server-side proxy, so this can stay narrow.
    # Comma-separated in the environment (CORS_ORIGINS=http://a,http://b) so the same .env
    # works when sourced by bash, included by make, and read by pydantic.
    cors_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
    readiness_timeout_s: float = 2.0
    # Ingestion limits (blueprint §13): whole request, and each stored payload/attribute map.
    max_ingest_bytes: int = 2_000_000
    max_event_payload_bytes: int = 32_768
    # Where checkpoint states (and later other artifacts) are written. Defaults inside the
    # repo's git-ignored data dir; tests point it at a temp dir.
    artifact_dir: Path = Field(
        default=REPO_ROOT / ".local-data" / "artifacts", validation_alias="BLACKBOX_ARTIFACT_DIR"
    )
    # Policy for reading analysis findings: projects whose findings may be served.
    # "*" = all (single-user local dev). Real per-user auth arrives in M10.
    findings_allowed_projects: Annotated[list[str], NoDecode] = ["*"]

    @field_validator("findings_allowed_projects", mode="before")
    @classmethod
    def _split_projects(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
