"""The extraction repository on SQLite.

Every method is one short transaction. The ones that decide something are one statement each, so two workers
or two requests at the same moment cannot both win: the claim, the terminal write, the release, the recovery,
the purge and the queue cap.
"""

from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import CursorResult, case, delete, func, insert, literal, select, update
from sqlalchemy.orm import aliased

from formlens.database import Database
from formlens.extractions.adapters.tables import ExtractionInputRow, ExtractionRow
from formlens.extractions.domain.exceptions import QUEUE_RETRY_AFTER_SECONDS, QueueFull
from formlens.extractions.domain.model import (
    FAILURE_MESSAGES,
    Extraction,
    ExtractionError,
    ExtractionStatus,
    FailureReason,
    RecoveryCounts,
    SnapshotField,
    TemplateSnapshot,
)


def _changed(result: Any) -> int:
    """Return how many rows a DML statement changed (a `Result` has no `rowcount`; a DML result does)."""
    return int(cast("CursorResult[Any]", result).rowcount)


def _fields_to_json(snapshot: TemplateSnapshot) -> list[dict[str, Any]]:
    return [
        {"name": item.name, "type": item.type, "description": item.description, "required": item.required}
        for item in snapshot.fields
    ]


def _to_extraction(row: ExtractionRow) -> Extraction:
    error = (
        ExtractionError(FailureReason(row.error_reason), row.error_message or "")
        if row.error_reason is not None
        else None
    )
    return Extraction(
        id=row.id,
        template=TemplateSnapshot(
            template_id=row.template_id,
            version=row.template_version,
            name=row.template_name,
            fields=tuple(SnapshotField(**item) for item in row.template_fields),
            json_schema=row.template_schema,
        ),
        status=ExtractionStatus(row.status),
        attempts=row.attempts,
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        result=row.result,
        error=error,
    )


class SqliteExtractionRepository:
    """Stores extractions and their uploads in SQLite."""

    def __init__(self, database: Database) -> None:
        """Use the sessions of `database`."""
        self._database = database

    def add(self, extraction: Extraction, content: bytes, *, max_pending: int) -> None:
        """Insert the extraction and its upload, unless `max_pending` extractions already wait.

        The guard of the queue cap: the count and the insert are one `INSERT ... SELECT ... WHERE (SELECT
        count(*) ...) < cap`. Counting first and inserting after would let every request that arrives
        together see room for itself.
        """
        columns = ExtractionRow.__table__.c
        values: dict[str, Any] = {
            "id": extraction.id,
            "template_id": extraction.template.template_id,
            "template_version": extraction.template.version,
            "template_name": extraction.template.name,
            "template_fields": _fields_to_json(extraction.template),
            "template_schema": extraction.template.json_schema,
            "status": extraction.status.value,
            "attempts": extraction.attempts,
            "created_at": extraction.created_at,
            "started_at": extraction.started_at,
            "finished_at": extraction.finished_at,
            "result": extraction.result,
            "error_reason": extraction.error.reason.value if extraction.error else None,
            "error_message": extraction.error.message if extraction.error else None,
        }
        pending = (
            select(func.count()).select_from(ExtractionRow).where(ExtractionRow.status == "pending").scalar_subquery()
        )
        room = select(*(literal(value, columns[name].type) for name, value in values.items())).where(
            pending < max_pending
        )
        with self._database.write() as session:
            if _changed(session.execute(insert(ExtractionRow).from_select(list(values), room))) == 0:
                raise QueueFull(QUEUE_RETRY_AFTER_SECONDS)
            session.add(ExtractionInputRow(extraction_id=extraction.id, content=content))

    def get(self, extraction_id: UUID) -> Extraction | None:
        """Read one extraction."""
        with self._database.read() as session:
            row = session.get(ExtractionRow, extraction_id)
            return _to_extraction(row) if row is not None else None

    def read_input(self, extraction_id: UUID) -> bytes | None:
        """Read the upload of a job that has not ended."""
        with self._database.read() as session:
            return session.scalar(
                select(ExtractionInputRow.content).where(ExtractionInputRow.extraction_id == extraction_id)
            )

    def claim_next(self, now: datetime) -> Extraction | None:
        """Take the oldest pending extraction in one UPDATE.

        The guard of "each job is claimed once": the row is chosen and changed by one statement, and the
        outer `status = 'pending'` predicate makes a second claim of the same row change nothing.
        """
        oldest = aliased(ExtractionRow)
        first_pending = (
            select(oldest.id).where(oldest.status == "pending").order_by(oldest.created_at, oldest.id).limit(1)
        ).scalar_subquery()
        with self._database.write() as session:
            row = session.execute(
                update(ExtractionRow)
                .where(ExtractionRow.id == first_pending, ExtractionRow.status == "pending")
                .values(status="running", attempts=ExtractionRow.attempts + 1, started_at=now)
                .returning(ExtractionRow)
            ).scalar_one_or_none()
            return _to_extraction(row) if row is not None else None

    def finish_if_running(self, finished: Extraction) -> bool:
        """Store the end of a job, only if it is still running with the same attempt count.

        The guard of "a late result changes nothing": the predicate is in the UPDATE, so a job that already
        failed as timed out, or was taken again, is not overwritten.
        """
        with self._database.write() as session:
            changed = _changed(
                session.execute(
                    update(ExtractionRow)
                    .where(
                        ExtractionRow.id == finished.id,
                        ExtractionRow.status == "running",
                        ExtractionRow.attempts == finished.attempts,
                    )
                    .values(
                        status=finished.status.value,
                        finished_at=finished.finished_at,
                        result=finished.result,
                        error_reason=finished.error.reason.value if finished.error else None,
                        error_message=finished.error.message if finished.error else None,
                    )
                )
            )
            if changed:
                session.execute(delete(ExtractionInputRow).where(ExtractionInputRow.extraction_id == finished.id))
            return changed > 0

    def release_if_running(self, released: Extraction, *, claimed_attempts: int) -> bool:
        """Put a running job back to pending, only if it is still running with `claimed_attempts`."""
        with self._database.write() as session:
            return (
                _changed(
                    session.execute(
                        update(ExtractionRow)
                        .where(
                            ExtractionRow.id == released.id,
                            ExtractionRow.status == "running",
                            ExtractionRow.attempts == claimed_attempts,
                        )
                        .values(status="pending", attempts=released.attempts, started_at=None)
                    )
                )
                > 0
            )

    def recover_running(self, max_attempts: int, now: datetime) -> RecoveryCounts:
        """Settle every running job in one UPDATE: pending if an attempt is left, else failed as interrupted."""
        left = ExtractionRow.attempts < max_attempts
        with self._database.write() as session:
            requeued = (
                session.scalar(
                    select(func.count()).select_from(ExtractionRow).where(ExtractionRow.status == "running", left)
                )
                or 0
            )
            changed = _changed(
                session.execute(
                    update(ExtractionRow)
                    .where(ExtractionRow.status == "running")
                    .values(
                        status=case((left, "pending"), else_="failed"),
                        started_at=None,
                        finished_at=case((left, None), else_=now),
                        error_reason=case((left, None), else_=FailureReason.INTERRUPTED.value),
                        error_message=case((left, None), else_=FAILURE_MESSAGES[FailureReason.INTERRUPTED]),
                    )
                )
            )
            session.execute(
                delete(ExtractionInputRow).where(
                    ExtractionInputRow.extraction_id.in_(
                        select(ExtractionRow.id).where(ExtractionRow.status.in_(("completed", "failed")))
                    )
                )
            )
            return RecoveryCounts(requeued=requeued, failed=changed - requeued)

    def purge_before(self, cutoff: datetime) -> int:
        """Delete the extractions that finished before `cutoff`; their uploads go with them."""
        with self._database.write() as session:
            session.execute(
                delete(ExtractionInputRow).where(
                    ExtractionInputRow.extraction_id.in_(
                        select(ExtractionRow.id).where(ExtractionRow.finished_at < cutoff)
                    )
                )
            )
            return _changed(session.execute(delete(ExtractionRow).where(ExtractionRow.finished_at < cutoff)))

    def count_pending(self) -> int:
        """Count the waiting extractions."""
        with self._database.read() as session:
            return (
                session.scalar(select(func.count()).select_from(ExtractionRow).where(ExtractionRow.status == "pending"))
                or 0
            )
