"""profiles and runs

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False, unique=True),
        sa.Column("host", sa.String(255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("dbname", sa.String(63), nullable=False),
        sa.Column("user", sa.String(63), nullable=False),
        sa.Column("sslmode", sa.String(16), nullable=False),
        sa.Column("app_name", sa.String(63), nullable=False),
        sa.Column("connect_timeout_s", sa.Integer(), nullable=False),
        sa.Column("password_enc", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "profile_id",
            sa.Integer(),
            sa.ForeignKey("profiles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("started_by", sa.String(64), nullable=True),
        sa.Column("stopped_by", sa.String(64), nullable=True),
        sa.Column("confirmed_rules_json", sa.Text(), nullable=True),
        sa.Column("config_json", sa.Text(), nullable=False),
        sa.Column("argv_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("server_version", sa.String(64), nullable=True),
        sa.Column("pgbench_version", sa.String(32), nullable=True),
        sa.Column("summary_json", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.CheckConstraint("kind IN ('init', 'bench')", name="ck_runs_kind"),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'finalizing', 'completed', 'failed', 'cancelled')",
            name="ck_runs_status",
        ),
    )
    op.create_index("ix_runs_profile_id", "runs", ["profile_id"])


def downgrade() -> None:
    op.drop_index("ix_runs_profile_id", table_name="runs")
    op.drop_table("runs")
    op.drop_table("profiles")
