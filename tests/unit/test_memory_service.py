import pytest

from models.enums import MemoryEnum
from services.memory_service import is_admin_memory, is_private


class TestIsAdminMemory:
    """Teste memory_service - is_admin_memory.

    Returns True only for memory kinds that are restricted to admin
    operations. Matching is exact (full-key equality), so unrelated or
    slightly malformed keys must not be treated as admin-only.
    """

    @pytest.mark.parametrize(
        "key",
        [
            MemoryEnum.FEATURES.value,
            MemoryEnum.GETNAME.value,
            MemoryEnum.PRESMED_FORM.value,
            MemoryEnum.SUMMARY_CONFIG.value,
            MemoryEnum.MAP_IV.value,
        ],
    )
    def test_admin_restricted_keys_return_true(self, key):
        """Known admin-restricted memory kinds are recognized"""
        assert is_admin_memory(key) is True

    @pytest.mark.parametrize(
        "key",
        [
            "user-preferences",
            "config-signature",
            "unknown-kind",
            "",
        ],
    )
    def test_non_admin_keys_return_false(self, key):
        """Keys that are not in the admin-restricted list are rejected"""
        assert is_admin_memory(key) is False

    def test_match_is_exact_not_substring(self):
        """Matching is exact: a key with extra characters is not admin-restricted"""
        assert is_admin_memory(MemoryEnum.FEATURES.value + " ") is False
        assert is_admin_memory("x" + MemoryEnum.FEATURES.value) is False


class TestIsPrivate:
    """Teste memory_service - is_private.

    Returns True when the memory kind is user-scoped (private to its owner).
    Matching is by substring, so any key that contains one of the private
    tokens is considered private.
    """

    @pytest.mark.parametrize(
        "key",
        [
            "config-signature",
            "filter-private",
            "user-preferences",
            "clinical-notes-private",
        ],
    )
    def test_exact_private_keys_return_true(self, key):
        """The canonical private memory kinds are recognized as private"""
        assert is_private(key) is True

    @pytest.mark.parametrize(
        "key",
        [
            "user-preferences-42",
            "prefix-config-signature",
            "clinical-notes-private-2024",
        ],
    )
    def test_substring_match_returns_true(self, key):
        """A key that merely contains a private token is treated as private"""
        assert is_private(key) is True

    @pytest.mark.parametrize(
        "key",
        [
            "features",
            "getnameurl",
            "summary-config",
            "",
        ],
    )
    def test_non_private_keys_return_false(self, key):
        """Keys without any private token are not private"""
        assert is_private(key) is False
