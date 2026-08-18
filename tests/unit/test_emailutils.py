"""Unit tests for the email format validation in utils.emailutils.

``is_valid_email`` is pure (no network, no database), so it is exercised
directly with plain strings.
"""

import pytest

from utils import emailutils


@pytest.mark.parametrize(
    "email",
    [
        "user@noharm.ai",
        "user.name@noharm.ai",
        "user+tag@noharm.ai",
        "user_name@noharm.ai",
        "user-name@noharm.ai",
        "user123@hospital.com.br",
        "u@sub.domain.hospital.com.br",
        "farmacia.clinica@hospital-sao-jose.com.br",
        "a" * 64 + "@noharm.ai",
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
        "joão@noharm.ai",
        "user@nóharm.ai",
        "usuário.teste@hospital.com.br",
        "ユーザー@noharm.ai",
        # invisible / control characters
        "user​@noharm.ai",
        "user@noharm.ai\n",
        "user\t@noharm.ai",
        "user name@noharm.ai",
        # spaces
        "user name@noharm.ai",
        " user@noharm.ai",
        "user@noharm.ai ",
        "user@ noharm.ai",
        # display name / angle brackets
        "Nome Sobrenome <user@noharm.ai>",
        "<user@noharm.ai>",
        '"user"@noharm.ai',
        # multiple addresses pasted in one field
        "user@noharm.ai,other@noharm.ai",
        "user@noharm.ai;other@noharm.ai",
        "user@noharm.ai other@noharm.ai",
        # structural problems
        "user",
        "user@",
        "@noharm.ai",
        "user@@noharm.ai",
        "user@noharm",
        "user@localhost",
        "user@noharm.a",
        "user@.noharm.ai",
        "user@noharm..ai",
        "user@noharm.ai.",
        "user@-noharm.ai",
        "user@noharm-.ai",
        ".user@noharm.ai",
        "user.@noharm.ai",
        "us..er@noharm.ai",
        # length limits
        "a" * 65 + "@noharm.ai",
        "a" * 250 + "@noharm.ai",
    ],
)
def test_invalid_emails(email):
    """Teste emailutils - is_valid_email rejeita endereços inválidos"""
    assert emailutils.is_valid_email(email) is False
