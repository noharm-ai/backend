"""Unit tests for the password strength rule used across the account endpoints.

``user_service.is_valid_password`` guards ``PUT /user`` and ``POST /user/reset``:
at least 8 characters with an uppercase letter, a lowercase letter and a digit.
"""

import pytest

from services.user_service import is_valid_password


@pytest.mark.parametrize(
    "password",
    [
        "Abcdefg1",  # exactly the minimum length
        "LongerPassword123",
        "aB3aB3aB",
        "Senha1Forte",
        "Ab1@#$%^&*",  # symbols are allowed
        "Ab1 with spaces",
    ],
)
def test_accepts_passwords_meeting_every_rule(password):
    """Passwords with 8+ chars, upper, lower and digit are accepted"""
    assert is_valid_password(password)


@pytest.mark.parametrize(
    ("password", "reason"),
    [
        ("Abc123", "shorter than 8 characters"),
        ("abcdefg1", "no uppercase letter"),
        ("ABCDEFG1", "no lowercase letter"),
        ("Abcdefgh", "no digit"),
        ("12345678", "digits only"),
        ("", "empty"),
        ("Abcdef1", "7 characters"),
    ],
)
def test_rejects_passwords_breaking_a_rule(password, reason):
    """Passwords missing any of the required character classes are rejected"""
    assert not is_valid_password(password), f"should be rejected: {reason}"


def test_rejects_newline_smuggled_after_a_valid_password():
    """A trailing newline must not let a weak tail slip past the rule (fullmatch)"""
    assert not is_valid_password("Abcdefg1\nweak")
