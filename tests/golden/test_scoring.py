"""The scoring: what counts as the right answer, and the two numbers that come out."""

from typing import Any

import pytest

from tests.golden.scoring import Report, normalise, percent, render_markdown, render_table, same, score_document

TYPES = {"name": "text", "amount": "number", "count": "integer", "ok": "boolean", "day": "date", "kind": "choice"}


@pytest.mark.parametrize(
    ("expected", "actual", "kind"),
    [
        ("Łódź", "łódź", "text"),
        ("Łódź", "  Łódź  ", "text"),
        ("Jan  Kowalski", "jan kowalski", "text"),
        ("Zażółć", "Zażółć", "text"),  # composed against decomposed letters
        (1234.56, 1234.56, "number"),
        (1234.56, 1234.558, "number"),
        (3, 3.0, "integer"),
        (True, True, "boolean"),
        ("2026-03-01", "2026-03-01", "date"),
        ("PLN", "pln", "choice"),
        (None, None, "text"),
    ],
)
def test_two_values_that_differ_only_in_case_spaces_or_letter_form_are_the_same(
    expected: Any, actual: Any, kind: str
) -> None:
    assert same(expected, actual, kind) is True


@pytest.mark.parametrize(
    ("expected", "actual", "kind"),
    [
        ("Łódź", "Lodz", "text"),
        (1234.56, 1234.57, "number"),
        (3, 4, "integer"),
        (True, False, "boolean"),
        ("2026-03-01", "2026-03-02", "date"),
        ("2026-03-01", "01.03.2026", "date"),
        (None, "x", "text"),
        ("x", None, "text"),
    ],
)
def test_two_values_that_differ_in_substance_are_not_the_same(expected: Any, actual: Any, kind: str) -> None:
    assert same(expected, actual, kind) is False


def test_none_stays_none_and_false_is_not_none() -> None:
    assert normalise(None, "boolean") is None
    assert normalise(False, "boolean") is False


def test_a_document_is_scored_field_by_field() -> None:
    results = score_document(
        "d1", {"name": "Ola", "amount": None, "ok": True}, {"name": "ola", "amount": 5, "ok": False}, TYPES
    )

    assert [(r.field, r.correct, r.invented) for r in results] == [
        ("name", True, False),
        ("amount", False, True),
        ("ok", False, False),
    ]


def test_a_failed_extraction_scores_every_field_wrong_even_a_null_one() -> None:
    results = score_document("d1", {"name": "Ola", "amount": None}, None, TYPES)

    assert [r.correct for r in results] == [False, False]
    assert [r.invented for r in results] == [False, False]


def report() -> Report:
    run = Report()
    run.add(
        score_document(
            "d1", {"name": "Ola", "amount": 10.0, "ok": None}, {"name": "ola", "amount": 11.0, "ok": None}, TYPES
        )
    )
    run.add(
        score_document(
            "d2", {"name": "Ewa", "amount": None, "ok": None}, {"name": "Ewa", "amount": 7.0, "ok": True}, TYPES
        )
    )
    run.add(score_document("d3", {"name": "Ada", "amount": 1.0, "ok": None}, None, TYPES), failed=True)
    return run


def test_exact_match_counts_only_fields_that_have_an_answer() -> None:
    run = report()

    # answers: d1 name (right), d1 amount (wrong), d2 name (right), d3 name and amount (failed): 2 of 5
    assert run.exact_match == pytest.approx(2 / 5)


def test_null_precision_counts_only_fields_without_an_answer_and_invented_values_are_counted() -> None:
    run = report()

    # empty fields: d1 ok (null, right), d2 amount (invented), d2 ok (invented), d3 ok (failed): 1 of 4
    assert run.null_precision == pytest.approx(1 / 4)
    assert run.invented == 2
    assert run.failed_documents == ["d3"]
    assert run.documents == 3


def test_the_rates_are_none_when_nothing_could_be_measured() -> None:
    empty = Report()

    assert (empty.exact_match, empty.null_precision, empty.invented) == (None, None, 0)
    assert percent(None) == "-"
    assert percent(0.5) == "50.0%"


def test_the_numbers_are_grouped_by_field_and_by_document() -> None:
    run = report()

    assert run.by_field() == {"amount": (0, 2), "name": (2, 3)}
    assert run.by_document() == {"d1": (2, 3), "d2": (1, 3), "d3": (0, 3)}


def test_the_markdown_says_what_was_measured_and_with_what() -> None:
    text = render_markdown(
        report(), model="qwen3:8b", prompt_version="field_extraction.v1", date="2026-11-11", digest="abc123"
    )

    assert "`qwen3:8b` (digest: abc123), prompt `field_extraction.v1`, 3 synthetic documents" in text
    assert "| Exact match (fields with an answer) | 40.0% |" in text
    assert "| Null precision (fields without an answer) | 25.0% |" in text
    assert "| Values invented for an empty field | 2 |" in text
    assert "| `name` | 2 | 3 | 66.7% |" in text


def test_the_table_for_the_terminal_lists_the_totals_and_every_document() -> None:
    text = render_table(report())

    assert "documents            3" in text
    assert "exact match          40.0%" in text
    assert "d3               0/3" in text
