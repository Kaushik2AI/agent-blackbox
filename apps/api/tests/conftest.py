"""Shared fixtures.

Integration tests run against the real Postgres/Redis named in .env, but inside a
separate database (`<name>_test`) that is created, migrated and dropped per session,
so your dev data is never touched.
"""

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

API_DIR = Path(__file__).resolve().parents[1]


def _alembic_config() -> Config:
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "migrations"))
    return cfg


@pytest.fixture(scope="session", autouse=True)
def artifact_dir(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """Checkpoint states written by tests go to a temp dir, never the dev data dir."""
    path = tmp_path_factory.mktemp("artifacts")
    previous = os.environ.get("BLACKBOX_ARTIFACT_DIR")
    os.environ["BLACKBOX_ARTIFACT_DIR"] = str(path)
    _clear_caches()
    yield path
    if previous is None:
        os.environ.pop("BLACKBOX_ARTIFACT_DIR", None)
    else:
        os.environ["BLACKBOX_ARTIFACT_DIR"] = previous
    _clear_caches()


@pytest.fixture(scope="session")
def test_database_url() -> Iterator[str]:
    from app.config import get_settings

    base_url = make_url(get_settings().database_url)
    test_db = f"{base_url.database}_test_{uuid.uuid4().hex[:8]}"
    admin = create_engine(base_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{test_db}"'))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Postgres not reachable for integration tests: {type(exc).__name__}")

    url = base_url.set(database=test_db).render_as_string(hide_password=False)
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    _clear_caches()
    try:
        yield url
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        _clear_caches()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{test_db}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture(scope="session")
def migrated_db(test_database_url: str) -> str:
    command.upgrade(_alembic_config(), "head")
    return test_database_url


@pytest.fixture
def alembic_cfg() -> Config:
    return _alembic_config()


def _clear_caches() -> None:
    from app import db
    from app.config import get_settings

    if db.get_engine.cache_info().currsize:
        db.get_engine().dispose()
    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db._session_factory.cache_clear()
