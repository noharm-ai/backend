"""Unit tests for the email format validation in utils.emailutils.

``is_valid_email`` is pure (no network, no database), so it is exercised
directly with plain strings.
"""

import pytest

from utils import emailutils


@pytest.mark.parametrize(
    "email",
    [
        "user@example.com",
        "user.name@example.com",
        "user+tag@example.com",
        "user_name@example.com",
        "user-name@example.com",
        "user123@hospital.com.br",
        "u@sub.domain.hospital.com.br",
        "farmacia.clinica@hospital-sao-jose.com.br",
        "a" * 64 + "@example.com",
    ],
)
def test_valid_emails(email):
    """Teste emailutils - is_valid_email aceita endereços válidos"""
    assert emailutils.is_valid_email(email) is True


@pytest.mark.parametrize(
    "email",
    [
        # empty / missing
        "",
        None,
        "   ",
        # accented and non-ascii characters
        "joão@example.com",
        "user@exámple.com",
        "usuário.teste@hospital.com.br",
        "ユーザー@example.com",
        # invisible / control characters
        "user​@example.com",
        "user@example.com\n",
        "user\t@example.com",
        "user name@example.com",
        # spaces
        "user name@example.com",
        " user@example.com",
        "user@example.com ",
        "user@ example.com",
        # display name / angle brackets
        "Nome Sobrenome <user@example.com>",
        "<user@example.com>",
        '"user"@example.com',
        # multiple addresses pasted in one field
        "user@example.com,other@example.com",
        "user@example.com;other@example.com",
        "user@example.com other@example.com",
        # structural problems
        "user",
        "user@",
        "@example.com",
        "user@@example.com",
        "user@example",
        "user@localhost",
        "user@example.a",
        "user@.example.com",
        "user@example..com",
        "user@example.com.",
        "user@-example.com",
        "user@example-.com",
        ".user@example.com",
        "user.@example.com",
        "us..er@example.com",
        # length limits
        "a" * 65 + "@example.com",
        "a" * 250 + "@example.com",
    ],
)
def test_invalid_emails(email):
    """Teste emailutils - is_valid_email rejeita endereços inválidos"""
    assert emailutils.is_valid_email(email) is False
