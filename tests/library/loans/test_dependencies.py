from datetime import date

from fastapi_szumplate.library.loans.dependencies import get_today


def test_the_default_clock_returns_a_date() -> None:
    assert isinstance(get_today()(), date)
