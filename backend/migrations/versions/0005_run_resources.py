"""run resources: agent CPU and RAM during a run

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "run_resources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("t_s", sa.Float(), nullable=False),
        sa.Column("cpu_pct", sa.Float(), nullable=False),
        sa.Column("ram_pct", sa.Float(), nullable=False),
        sa.Column("ram_used_bytes", sa.BigInteger(), nullable=False),
    )
    op.create_index("ix_runs_created_at", "runs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_runs_created_at", "runs")
    op.drop_table("run_resources")
