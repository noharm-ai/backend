import re

import pytest

from utils import certificateutils


def test_generate_code_length_and_alphabet():
    """Codes are 12 characters drawn only from the Crockford alphabet."""
    for _ in range(50):
        code = certificateutils.generate_code()

        assert len(code) == certificateutils.CODE_LENGTH
        assert re.fullmatch(f"[{certificateutils.ALPHABET}]+", code)


def test_generate_code_excludes_the_ambiguous_characters():
    """I, L, O and U never appear: they are what gets misread off paper."""
    generated = "".join(certificateutils.generate_code() for _ in range(200))

    for char in "ILOU":
        assert char not in generated


@pytest.mark.parametrize(
    "typed, expected",
    [
        ("ABCD-EFGH-JKMN", "ABCDEFGHJKMN"),
        ("abcd-efgh-jkmn", "ABCDEFGHJKMN"),
        ("abcd efgh jkmn", "ABCDEFGHJKMN"),
        ("ABCDEFGHJKMN", "ABCDEFGHJKMN"),
        # the fold has to happen before the strip, or these characters would be
        # dropped instead of rescued
        ("OI1L", "0111"),
        ("oi1l", "0111"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalize_code(typed, expected):
    """Whatever a human types off a printed certificate resolves to the code."""
    assert certificateutils.normalize_code(typed) == expected


def test_normalize_code_survives_junk():
    assert certificateutils.normalize_code("!!! ###") == ""


@pytest.mark.parametrize(
    "code, expected",
    [
        ("ABCDEFGHJKMN", "ABCD-EFGH-JKMN"),
        ("", ""),
    ],
)
def test_format_code(code, expected):
    assert certificateutils.format_code(code) == expected


def test_format_then_normalize_round_trips():
    """The printed form always resolves back to what is stored."""
    code = certificateutils.generate_code()

    assert certificateutils.normalize_code(certificateutils.format_code(code)) == code
