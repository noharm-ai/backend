"""Unit tests for services.navigation_service._encrypt_clinical_notes.

The helper prepares clinical-notes text for the copy-patient Lambda payload: it
truncates each note to 5000 characters and Fernet-encrypts it, while dropping any
non-string value. These tests exercise it in isolation, without touching AWS.
"""

import base64

import pytest
from cryptography.fernet import Fernet

from config import Config
from services import navigation_service


@pytest.fixture
def fernet_key(monkeypatch):
    """Configure a valid Fernet key on Config and return the Fernet helper for decryption."""
    key = Fernet.generate_key()
    monkeypatch.setattr(Config, "ENCRYPTION_KEY", key.decode("utf-8"))
    return Fernet(key)


def _decrypt(fernet, ciphertext):
    """Reverse cryptutils.encrypt_data: base64-decode then Fernet-decrypt."""
    inner = base64.b64decode(ciphertext.encode("utf-8"))
    return fernet.decrypt(inner).decode("utf-8")


@pytest.mark.parametrize("bad_input", [None, "", "a string", 123, [], ["a"]])
def test_returns_empty_dict_for_non_dict_input(bad_input):
    """Anything that is not a (non-empty) dict yields an empty dict."""
    assert navigation_service._encrypt_clinical_notes(bad_input) == {}


def test_empty_dict_returns_empty_dict():
    """An empty dict produces an empty dict (nothing to encrypt)."""
    assert navigation_service._encrypt_clinical_notes({}) == {}


def test_string_values_are_encrypted_and_roundtrip(fernet_key):
    """Each string note is encrypted and decrypts back to the original text."""
    notes = {"evolution": "patient stable", "allergies": "none reported"}

    result = navigation_service._encrypt_clinical_notes(notes)

    assert set(result.keys()) == {"evolution", "allergies"}
    for key, plaintext in notes.items():
        assert result[key] != plaintext  # actually encrypted
        assert _decrypt(fernet_key, result[key]) == plaintext


def test_non_string_values_become_none(fernet_key):  # noqa: ARG001
    """Non-string values (numbers, None, empty string, nested dicts) map to None."""
    notes = {
        "a": 42,
        "b": None,
        "c": "",
        "d": {"nested": "x"},
        "e": ["list"],
    }

    result = navigation_service._encrypt_clinical_notes(notes)

    assert result == {"a": None, "b": None, "c": None, "d": None, "e": None}


def test_mixed_values(fernet_key):
    """A mix of string and non-string values encrypts the strings and nulls the rest."""
    notes = {"text": "important note", "count": 5}

    result = navigation_service._encrypt_clinical_notes(notes)

    assert result["count"] is None
    assert _decrypt(fernet_key, result["text"]) == "important note"


def test_long_text_is_truncated_before_encryption(fernet_key):
    """Text over 5000 chars is truncated (with a marker) before being encrypted."""
    long_text = "palavra " * 1000  # ~8000 characters

    result = navigation_service._encrypt_clinical_notes({"note": long_text})

    decrypted = _decrypt(fernet_key, result["note"])
    assert len(decrypted) <= 5000
    assert decrypted.endswith("... [truncado]")
    assert decrypted != long_text
