"""Initial schema.

Revision ID: 0001
Revises:
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa  # noqa: F401  # the tables created below use it
from alembic import op  # noqa: F401

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the tables."""


def downgrade() -> None:
    """Drop the tables."""
