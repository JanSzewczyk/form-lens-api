"""The `extractions` table and the `extraction_inputs` table that holds an upload while its job waits."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, Integer, LargeBinary, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from formlens.database import Base, UtcDateTime


class ExtractionRow(Base):
    """One extraction.

    The template is a copy (`template_*` columns), not a foreign key: deleting or editing the template never
    touches a queued or finished job. `status` and `attempts` carry the rules of the queue as CHECKs.
    """

    __tablename__ = "extractions"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'running', 'completed', 'failed')", name="status_known"),
        CheckConstraint("attempts >= 0", name="attempts_not_negative"),
        # Claim (oldest pending first) and the queue count read the pending rows in creation order.
        Index("ix_extractions_status_created_at_id", "status", "created_at", "id"),
        # The purge and the expiry read by the time a job finished.
        Index("ix_extractions_finished_at", "finished_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    template_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    template_version: Mapped[int] = mapped_column(Integer, nullable=False)
    template_name: Mapped[str] = mapped_column(String(100), nullable=False)
    template_fields: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    template_schema: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    # `none_as_null`: no result is SQL NULL, not the JSON value `null`.
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON(none_as_null=True), nullable=True)
    error_reason: Mapped[str | None] = mapped_column(String(30), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(200), nullable=True)


class ExtractionInputRow(Base):
    """The upload of a job that has not ended; deleted at the end, and with the extraction."""

    __tablename__ = "extraction_inputs"

    extraction_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("extractions.id", ondelete="CASCADE"), primary_key=True
    )
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
