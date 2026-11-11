"""Scoring an extraction against the answer: exact match after normalisation, and what is invented.

Two numbers matter. *Exact match* is the share of the fields that have an answer which the model got right.
*Null precision* is the share of the fields that have no answer (the document does not show them) which the
model left `null`; the rest it invented. A model that always guesses scores well on the first and badly on the
second, which is why they are reported apart. A document the extraction failed on counts every field as wrong.
"""

import math
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Final

_NUMBER_TOLERANCE: Final = 0.005  # half a grosz


def normalise(value: Any, field_type: str) -> Any:
    """Bring a value to the form it is compared in; `None` stays `None`.

    Text is compared without case, without a difference between composed and decomposed letters and with runs
    of spaces folded. Numbers are compared as numbers, dates and choices as normalised text.
    """
    if value is None:
        return None
    if field_type in {"number", "integer"}:
        return float(value)
    if field_type == "boolean":
        return bool(value)
    return " ".join(unicodedata.normalize("NFC", str(value)).casefold().split())


def same(expected: Any, actual: Any, field_type: str) -> bool:
    """Tell whether two values are equal after normalisation."""
    left, right = normalise(expected, field_type), normalise(actual, field_type)
    if isinstance(left, float) and isinstance(right, float):
        return math.isclose(left, right, abs_tol=_NUMBER_TOLERANCE)
    return bool(left == right)


@dataclass(frozen=True, slots=True)
class FieldResult:
    """How one field of one document went."""

    document: str
    field: str
    expected: Any
    actual: Any
    correct: bool

    @property
    def expected_null(self) -> bool:
        """Tell whether the document does not show this field."""
        return self.expected is None

    @property
    def invented(self) -> bool:
        """Tell whether the model gave a value for a field the document does not show."""
        return self.expected is None and self.actual is not None


def score_document(
    document: str, expected: dict[str, Any], actual: dict[str, Any] | None, types: dict[str, str]
) -> list[FieldResult]:
    """Compare every field; `actual` is `None` for a document the extraction failed on."""
    return [
        FieldResult(
            document=document,
            field=name,
            expected=value,
            actual=None if actual is None else actual.get(name),
            correct=actual is not None and same(value, actual.get(name), types[name]),
        )
        for name, value in expected.items()
    ]


@dataclass(slots=True)
class Report:
    """The results of a run, and the numbers computed from them."""

    results: list[FieldResult] = field(default_factory=list)
    failed_documents: list[str] = field(default_factory=list)
    documents: int = 0

    def add(self, results: list[FieldResult], *, failed: bool = False) -> None:
        """Record one document."""
        self.documents += 1
        self.results.extend(results)
        if failed and results:
            self.failed_documents.append(results[0].document)

    @staticmethod
    def _rate(hits: int, total: int) -> float | None:
        return hits / total if total else None

    @property
    def exact_match(self) -> float | None:
        """Share of the fields with an answer that the model got right."""
        answered = [r for r in self.results if not r.expected_null]
        return self._rate(sum(r.correct for r in answered), len(answered))

    @property
    def null_precision(self) -> float | None:
        """Share of the fields without an answer that the model left `null`."""
        blank = [r for r in self.results if r.expected_null]
        return self._rate(sum(r.correct for r in blank), len(blank))

    @property
    def invented(self) -> int:
        """Number of values given for fields the document does not show."""
        return sum(r.invented for r in self.results)

    def by_field(self) -> dict[str, tuple[int, int]]:
        """Return `(right, total)` of the fields that have an answer, by field name."""
        counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for result in self.results:
            if not result.expected_null:
                counts[result.field][0] += result.correct
                counts[result.field][1] += 1
        return {name: (right, total) for name, (right, total) in sorted(counts.items())}

    def by_document(self) -> dict[str, tuple[int, int]]:
        """Return `(right, total)` of all fields, by document, in the order they were recorded."""
        counts: dict[str, list[int]] = {}
        for result in self.results:
            entry = counts.setdefault(result.document, [0, 0])
            entry[0] += result.correct
            entry[1] += 1
        return {name: (right, total) for name, (right, total) in counts.items()}


def percent(value: float | None) -> str:
    """Write a rate as a percentage, or a dash when there was nothing to measure."""
    return "-" if value is None else f"{value * 100:.1f}%"


def render_markdown(report: Report, *, model: str, prompt_version: str, date: str, digest: str = "not recorded") -> str:
    """Write the README's accuracy section for a run: the setup, the totals and one row per field."""
    lines = [
        (
            f"Measured on {date} with `{model}` (digest: {digest}), prompt `{prompt_version}`, "
            f"{report.documents} synthetic documents."
        ),
        "",
        "| Measure | Value |",
        "| --- | --- |",
        f"| Exact match (fields with an answer) | {percent(report.exact_match)} |",
        f"| Null precision (fields without an answer) | {percent(report.null_precision)} |",
        f"| Values invented for an empty field | {report.invented} |",
        f"| Documents the extraction failed on | {len(report.failed_documents)} |",
        "",
        "| Field | Right | Total | Exact match |",
        "| --- | --- | --- | --- |",
    ]
    lines += [
        f"| `{name}` | {right} | {total} | {percent(right / total)} |"
        for name, (right, total) in report.by_field().items()
    ]
    return "\n".join(lines) + "\n"


def render_table(report: Report) -> str:
    """Write the totals and the per-document lines as plain text for the terminal."""
    lines = [
        f"documents            {report.documents}",
        f"exact match          {percent(report.exact_match)}",
        f"null precision       {percent(report.null_precision)}",
        f"invented values      {report.invented}",
        f"failed documents     {len(report.failed_documents)}",
        "",
        "document         right/total",
    ]
    lines += [f"{name:<16} {right}/{total}" for name, (right, total) in report.by_document().items()]
    return "\n".join(lines)
