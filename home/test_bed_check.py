import pytest

from bed_check import parse_answer


@pytest.mark.parametrize("text,expected", [("yes", "yes"), ("No.\n", "no"), (" YES。", "yes")])
def test_parse_answer(text, expected):
    assert parse_answer(text) == expected


@pytest.mark.parametrize("text", ["", "yes, it is", "たぶん no"])
def test_parse_answer_rejects_other_text(text):
    with pytest.raises(RuntimeError):
        parse_answer(text)
