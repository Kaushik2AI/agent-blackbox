"""m8 evaluation runs

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-16 20:10:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "evaluation_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_key", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("benchmark_version", sa.String(length=64), nullable=False),
        sa.Column("case_id", sa.String(length=128), nullable=False),
        sa.Column("family", sa.String(length=64), nullable=False),
        sa.Column("split", sa.String(length=16), nullable=False),
        sa.Column("arm", sa.String(length=16), nullable=False),
        sa.Column("model_spec", sa.String(length=200), nullable=False),
        sa.Column("model_id", sa.String(length=200), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=True),
        sa.Column("record_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "imported_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_key"),
    )
    op.create_index("ix_evaluation_runs_source", "evaluation_runs", ["source"])


def downgrade() -> None:
    op.drop_index("ix_evaluation_runs_source", table_name="evaluation_runs")
    op.drop_table("evaluation_runs")
