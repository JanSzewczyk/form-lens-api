"""Regular expressions that come from a client, matched in linear time.

A template's `pattern` is written by a client and runs on text the client does not control. Python's `re` can
take exponential time on a pattern such as `(a+)+$` (about 5 s for 26 characters, minutes for 30), and a thread
stuck in it cannot be stopped: the worker would never take another job. The Rust engine of `pydantic-core`
matches in linear time and refuses lookaround and backreferences, so every pattern that is accepted here is
safe to run. Matching is a search, as in JSON Schema: the pattern may match anywhere unless it is anchored.
"""

from functools import lru_cache

from pydantic_core import CoreConfig, SchemaError, SchemaValidator, ValidationError, core_schema


class UnsupportedPattern(ValueError):
    """The pattern is not valid, or uses a feature the linear-time engine does not have."""


@lru_cache(maxsize=512)
def _validator(pattern: str) -> SchemaValidator:
    try:
        return SchemaValidator(core_schema.str_schema(pattern=pattern), CoreConfig(regex_engine="rust-regex"))
    except SchemaError:
        raise UnsupportedPattern from None


def check_pattern(pattern: str) -> None:
    """Raise `UnsupportedPattern` unless `pattern` compiles in the linear-time engine."""
    _validator(pattern)


def matches(pattern: str, text: str) -> bool:
    """Tell whether `pattern` is found in `text`; raise `UnsupportedPattern` for a pattern that does not compile."""
    try:
        _validator(pattern).validate_python(text)
    except ValidationError:
        return False
    return True
