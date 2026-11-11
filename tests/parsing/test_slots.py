import pytest

from formlens.parsing.exceptions import ParserBusy
from formlens.parsing.slots import ParseSlots


def test_a_free_slot_is_taken_and_given_back() -> None:
    slots = ParseSlots(1)

    with slots.hold():
        pass
    with slots.hold():
        pass


def test_a_caller_that_finds_no_free_slot_is_refused_at_once() -> None:
    slots = ParseSlots(1)

    with slots.hold(), pytest.raises(ParserBusy, match="busy"), slots.hold():
        pass


def test_a_slot_is_given_back_when_the_body_raises() -> None:
    slots = ParseSlots(1)

    with pytest.raises(RuntimeError, match="boom"), slots.hold():
        raise RuntimeError("boom")

    with slots.hold():
        pass


def test_as_many_slots_are_free_as_were_asked_for() -> None:
    slots = ParseSlots(2)

    with slots.hold(), slots.hold(), pytest.raises(ParserBusy), slots.hold():
        pass


def test_a_refused_caller_does_not_free_a_slot_it_never_held() -> None:
    slots = ParseSlots(1)

    with slots.hold():
        with pytest.raises(ParserBusy), slots.hold():
            pass
        with pytest.raises(ParserBusy), slots.hold():
            pass
