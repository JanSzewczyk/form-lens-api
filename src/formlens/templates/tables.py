"""The `templates` table."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, CheckConstraint, Index, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from formlens.database import Base, UtcDateTime


class TemplateRow(Base):
    """A template; `fields` is the list of field definitions as JSON, read and written as a whole."""

    __tablename__ = "templates"
    __table_args__ = (
        CheckConstraint("version >= 1", name="version_positive"),
        Index("ix_templates_created_at_id", "created_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    fields: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
