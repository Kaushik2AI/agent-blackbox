"""Database integration: real migrations against real Postgres, plus FK behaviour."""

import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Agent, AgentVersion, Execution, ExecutionStatus, Project

pytestmark = pytest.mark.integration


def _seed(session: Session) -> tuple[Project, AgentVersion]:
    project = Project(name=f"p-{uuid.uuid4().hex[:6]}", owner_id="dev")
    session.add(project)
    session.flush()
    agent = Agent(project_id=project.id, name="support-agent")
    session.add(agent)
    session.flush()
    version = AgentVersion(
        agent_id=agent.id, git_sha="a" * 40, config_hash="b" * 64, model_name="stub"
    )
    session.add(version)
    session.flush()
    return project, version


def test_migration_creates_expected_tables(migrated_db: str) -> None:
    tables = set(inspect(create_engine(migrated_db)).get_table_names())
    assert {"projects", "agents", "agent_versions", "executions", "alembic_version"} <= tables


def test_execution_roundtrip_with_fork_lineage(migrated_db: str) -> None:
    engine = create_engine(migrated_db)
    with Session(engine) as session, session.begin():
        project, version = _seed(session)
        parent = Execution(
            project_id=project.id,
            agent_version_id=version.id,
            task_id="fixture-ok",
            status=ExecutionStatus.FAILED,
        )
        session.add(parent)
        session.flush()
        child = Execution(
            project_id=project.id,
            agent_version_id=version.id,
            task_id="fixture-ok",
            parent_execution_id=parent.id,
        )
        session.add(child)
        session.flush()
        child_id, parent_id = child.id, parent.id

    with Session(engine) as session:
        loaded = session.scalars(select(Execution).where(Execution.id == child_id)).one()
        assert loaded.parent_execution_id == parent_id
        assert loaded.status is ExecutionStatus.PENDING


def test_foreign_keys_are_enforced(migrated_db: str) -> None:
    engine = create_engine(migrated_db)
    with Session(engine) as session:
        session.add(Execution(project_id=uuid.uuid4(), agent_version_id=uuid.uuid4(), task_id="x"))
        with pytest.raises(IntegrityError):
            session.flush()


def test_execution_cannot_be_its_own_parent(migrated_db: str) -> None:
    engine = create_engine(migrated_db)
    with Session(engine) as session:
        project, version = _seed(session)
        own_id = uuid.uuid4()
        session.add(
            Execution(
                id=own_id,
                project_id=project.id,
                agent_version_id=version.id,
                task_id="x",
                parent_execution_id=own_id,
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()


def test_downgrade_then_upgrade_is_clean(migrated_db: str, alembic_cfg: Config) -> None:
    command.downgrade(alembic_cfg, "base")
    assert "executions" not in inspect(create_engine(migrated_db)).get_table_names()
    command.upgrade(alembic_cfg, "head")
    assert "executions" in inspect(create_engine(migrated_db)).get_table_names()
