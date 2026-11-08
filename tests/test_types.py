from datetime import UTC, date, datetime

import pytest
from pydantic import BaseModel, ValidationError

from formlens.types import IsoAwareDatetime, IsoDate, WholeNumber


class Dated(BaseModel):
    day: IsoDate


class Stamped(BaseModel):
    at: IsoAwareDatetime


def test_iso_date_string_is_accepted() -> None:
    assert Dated.model_validate({"day": "2026-11-07"}).day.isoformat() == "2026-11-07"


@pytest.mark.parametrize(
    "value",
    [0, 1, 1.5, "2026-11-07T10:00:00", "20261107", "07-11-2026", "", None],
    ids=["zero", "one", "float", "datetime-string", "compact", "reversed", "empty", "none"],
)
def test_anything_but_an_iso_date_is_rejected(value: object) -> None:
    with pytest.raises(ValidationError, match="ISO 8601"):
        Dated.model_validate({"day": value})


def test_aware_datetime_with_offset_is_accepted() -> None:
    parsed = Stamped.model_validate({"at": "2026-11-07T10:00:00+01:00"})

    assert parsed.at.utcoffset() is not None


@pytest.mark.parametrize(
    "value",
    [0, 1_700_000_000, "2026-11-07", None],
    ids=["zero", "epoch", "date-only", "none"],
)
def test_numbers_and_bare_dates_are_not_datetimes(value: object) -> None:
    with pytest.raises(ValidationError, match="ISO 8601"):
        Stamped.model_validate({"at": value})


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        Stamped.model_validate({"at": "2026-11-07T10:00:00"})


def test_python_date_and_aware_datetime_objects_are_accepted() -> None:
    assert Dated(day=date(2026, 11, 7)).day == date(2026, 11, 7)
    assert Stamped(at=datetime(2026, 11, 7, tzinfo=UTC)).at.year == 2026


class Counted(BaseModel):
    count: WholeNumber


@pytest.mark.parametrize(("value", "expected"), [(3, 3), (3.0, 3), (-2.0, -2)])
def test_whole_numbers_are_accepted_also_as_floats(value: float, expected: int) -> None:
    assert Counted.model_validate({"count": value}).count == expected


@pytest.mark.parametrize("value", ["3", 3.5, True, None, float("inf"), float("nan")], ids=repr)
def test_strings_fractions_and_booleans_are_not_whole_numbers(value: object) -> None:
    with pytest.raises(ValidationError, match="whole number"):
        Counted.model_validate({"count": value})
