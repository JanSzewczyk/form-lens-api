"""Initial schema: templates, extractions and the uploads that wait for a worker.

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

    op.create_table(
        "extractions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("template_id", sa.Uuid(), nullable=False),
        sa.Column("template_version", sa.Integer(), nullable=False),
        sa.Column("template_name", sa.String(length=100), nullable=False),
        sa.Column("template_fields", sa.JSON(), nullable=False),
        sa.Column("template_schema", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("error_reason", sa.String(length=30), nullable=True),
        sa.Column("error_message", sa.String(length=200), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')", name=op.f("ck_extractions_status_known")
        ),
        sa.CheckConstraint("attempts >= 0", name=op.f("ck_extractions_attempts_not_negative")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_extractions")),
    )
    op.create_index("ix_extractions_status_created_at_id", "extractions", ["status", "created_at", "id"])
    op.create_index("ix_extractions_finished_at", "extractions", ["finished_at"])
    op.create_table(
        "extraction_inputs",
        sa.Column("extraction_id", sa.Uuid(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.ForeignKeyConstraint(
            ["extraction_id"],
            ["extractions.id"],
            name=op.f("fk_extraction_inputs_extraction_id_extractions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("extraction_id", name=op.f("pk_extraction_inputs")),
    )


def downgrade() -> None:
    """Drop the tables."""
    op.drop_table("extraction_inputs")
    op.drop_index("ix_extractions_finished_at", table_name="extractions")
    op.drop_index("ix_extractions_status_created_at_id", table_name="extractions")
    op.drop_table("extractions")
    op.drop_index("ix_templates_created_at_id", table_name="templates")
    op.drop_table("templates")
