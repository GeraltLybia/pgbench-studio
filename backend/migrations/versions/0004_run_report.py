"""run report: series, statements, histogram

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _run_id() -> sa.Column[int]:
    return sa.Column(
        "run_id",
        sa.Integer(),
        sa.ForeignKey("runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


def upgrade() -> None:
    op.create_table(
        "run_series",
        sa.Column("id", sa.Integer(), primary_key=True),
        _run_id(),
        sa.Column("t_s", sa.Integer(), nullable=False),
        sa.Column("tx", sa.Integer(), nullable=False),
        sa.Column("tps", sa.Float(), nullable=False),
        sa.Column("lat_avg_ms", sa.Float(), nullable=True),
        sa.Column("lat_min_ms", sa.Float(), nullable=True),
        sa.Column("lat_max_ms", sa.Float(), nullable=True),
        sa.Column("lat_std_ms", sa.Float(), nullable=True),
        sa.Column("lag_ms", sa.Float(), nullable=True),
        sa.Column("failed", sa.Integer(), nullable=False),
        sa.Column("retried", sa.Integer(), nullable=False),
    )
    op.create_table(
        "run_statements",
        sa.Column("id", sa.Integer(), primary_key=True),
        _run_id(),
        sa.Column("script", sa.String(128), nullable=False),
        sa.Column("idx", sa.Integer(), nullable=False),
        sa.Column("sql", sa.Text(), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("failures", sa.Integer(), nullable=True),
    )
    op.create_table(
        "run_histogram",
        sa.Column("id", sa.Integer(), primary_key=True),
        _run_id(),
        sa.Column("bucket_upper_ms", sa.Float(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("run_histogram")
    op.drop_table("run_statements")
    op.drop_table("run_series")
