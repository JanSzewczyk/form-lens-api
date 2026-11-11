"""Client patterns run in linear time: a pathological one finishes at once and an unsupported one is refused."""

import time

import pytest

from formlens.patterns import UnsupportedPattern, check_pattern, matches


@pytest.mark.parametrize(
    ("pattern", "text", "found"),
    [
        ("^[0-9]{11}$", "44051401359", True),
        ("^[0-9]{11}$", "4405140135", False),
        ("b", "abc", True),  # a search, not an anchored match
        ("^b", "abc", False),
        (r"\d{3}", "x123", True),
        ("c$", "abc\n", False),
    ],
)
def test_a_pattern_is_searched_in_the_text(pattern: str, text: str, found: bool) -> None:
    assert matches(pattern, text) is found


@pytest.mark.parametrize(
    "pattern", ["(a+)+$", "(a|aa)+$", "(a*)*b", "(.*a){20}"], ids=["nested", "alternation", "star-star", "counted"]
)
def test_a_pattern_that_takes_exponential_time_in_python_re_finishes_at_once(pattern: str) -> None:
    text = "a" * 20000 + "!"
    started = time.perf_counter()

    assert matches(pattern, text) in {True, False}

    assert time.perf_counter() - started < 1.0


@pytest.mark.parametrize(
    "pattern",
    ["(?=a)a", "(?!a)b", "(?<=a)b", r"(a)\1", "[", "(", "a{4294967295}", "(a{1000}){1000}"],
    ids=[
        "lookahead",
        "negative-lookahead",
        "lookbehind",
        "backreference",
        "open-class",
        "open-group",
        "huge-repeat",
        "huge-nesting",
    ],
)
def test_a_pattern_the_linear_engine_cannot_compile_is_refused(pattern: str) -> None:
    with pytest.raises(UnsupportedPattern):
        check_pattern(pattern)
    with pytest.raises(UnsupportedPattern):
        matches(pattern, "a")
