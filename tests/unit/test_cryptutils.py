"""Unit tests for utils.cryptutils.encrypt_data (Fernet symmetric encryption)."""

import base64

import pytest
from cryptography.fernet import Fernet

from config import Config
from utils import cryptutils


@pytest.fixture
def fernet_key(monkeypatch):
    """Configure a valid Fernet key on Config and return the Fernet helper."""
    key = Fernet.generate_key()
    monkeypatch.setattr(Config, "ENCRYPTION_KEY", key.decode("utf-8"))
    return Fernet(key)


@pytest.mark.parametrize("empty", [None, ""])
def test_encrypt_data_returns_none_for_empty_input(empty):
    """Empty or missing plaintext short-circuits to None without touching the key."""
    assert cryptutils.encrypt_data(empty) is None


def test_encrypt_data_raises_when_key_missing(monkeypatch):
    """A missing ENCRYPTION_KEY raises ValueError before any encryption happens."""
    monkeypatch.setattr(Config, "ENCRYPTION_KEY", None)

    with pytest.raises(ValueError, match="ENCRYPTION_KEY not set"):
        cryptutils.encrypt_data("sensitive")


def test_encrypt_data_roundtrips_to_original(fernet_key):
    """The ciphertext is base64-wrapped Fernet output that decrypts to the input."""
    plaintext = "generic-placeholder-value-ção"

    ciphertext = cryptutils.encrypt_data(plaintext)

    assert isinstance(ciphertext, str)
    assert ciphertext != plaintext
    inner = base64.b64decode(ciphertext.encode("utf-8"))
    assert fernet_key.decrypt(inner).decode("utf-8") == plaintext


def test_encrypt_data_produces_distinct_ciphertexts(fernet_key):
    """Fernet embeds a random IV, so repeated encryption yields different output."""
    plaintext = "repeatable-value"

    first = cryptutils.encrypt_data(plaintext)
    second = cryptutils.encrypt_data(plaintext)

    assert first != second
    # Both must still decrypt back to the same plaintext.
    for ciphertext in (first, second):
        inner = base64.b64decode(ciphertext.encode("utf-8"))
        assert fernet_key.decrypt(inner).decode("utf-8") == plaintext


def test_encrypt_data_raises_on_invalid_key(monkeypatch):
    """A malformed ENCRYPTION_KEY surfaces as a friendly ValueError, not a crash."""
    monkeypatch.setattr(Config, "ENCRYPTION_KEY", "not-a-valid-fernet-key")

    with pytest.raises(ValueError, match="Erro ao criptografar dados sensíveis"):
        cryptutils.encrypt_data("sensitive")
