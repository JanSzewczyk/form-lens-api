"""Initial schema: templates.

Revision ID: 0001
Revises:
Create Date: 2026-11-11

Stage 2 is not released, so the tables of its later steps are added to this revision rather than to new ones.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the tables."""
    op.create_table(
        "templates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=300), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("fields", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version >= 1", name=op.f("ck_templates_version_positive")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_templates")),
    )
    op.create_index("ix_templates_created_at_id", "templates", ["created_at", "id"])


def downgrade() -> None:
    """Drop the tables."""
    op.drop_index("ix_templates_created_at_id", table_name="templates")
    op.drop_table("templates")
