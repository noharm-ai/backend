"""Unit tests for the role/feature validation helpers in user_admin_service.

These cover the pure functions used while upserting a user's configuration:

- ``_remove_legacy_roles``   strips deprecated role names before persisting.
- ``_has_valid_roles``       rejects any role that is not an assignable Role.
- ``_has_valid_features``    rejects any feature outside the assignable set.

All three are pure (no database / no request context), so they are exercised
directly with plain Python lists.
"""

import pytest

from models.enums import FeatureEnum
from security.role import Role
from services import user_admin_service


class TestRemoveLegacyRoles:
    """Teste user_admin_service - _remove_legacy_roles"""

    def test_removes_known_legacy_roles(self):
        """Deprecated role names are stripped from the list."""
        roles = ["cpoe", "readonly", "userAdmin", "suporte"]
        assert user_admin_service._remove_legacy_roles(roles) == []

    def test_keeps_valid_roles(self):
        """Assignable (non-legacy) roles are preserved."""
        roles = [Role.PRESCRIPTION_ANALYST.value, Role.CONFIG_MANAGER.value]
        assert user_admin_service._remove_legacy_roles(roles) == [
            Role.PRESCRIPTION_ANALYST.value,
            Role.CONFIG_MANAGER.value,
        ]

    def test_mixed_list_only_drops_legacy(self):
        """A mix keeps valid roles and drops only the legacy ones, preserving order."""
        roles = ["cpoe", Role.VIEWER.value, "readonly", Role.USER_MANAGER.value]
        assert user_admin_service._remove_legacy_roles(roles) == [
            Role.VIEWER.value,
            Role.USER_MANAGER.value,
        ]

    def test_empty_list_returns_empty(self):
        """An empty list stays empty."""
        assert user_admin_service._remove_legacy_roles([]) == []

    def test_returns_same_list_instance(self):
        """The function mutates and returns the same list object it was given."""
        roles = ["cpoe", Role.VIEWER.value]
        result = user_admin_service._remove_legacy_roles(roles)
        assert result is roles


class TestHasValidRoles:
    """Teste user_admin_service - _has_valid_roles"""

    @pytest.mark.parametrize(
        "role",
        [
            Role.PRESCRIPTION_ANALYST.value,
            Role.CONFIG_MANAGER.value,
            Role.DISCHARGE_MANAGER.value,
            Role.USER_MANAGER.value,
            Role.VIEWER.value,
            Role.DISPENSING_MANAGER.value,
            Role.REGULATOR.value,
            Role.SUPPORT_REQUESTER.value,
            Role.SUPPORT_MANAGER.value,
        ],
    )
    def test_each_assignable_role_is_valid(self, role):
        """Every assignable role passes validation on its own."""
        assert user_admin_service._has_valid_roles([role]) is True

    def test_all_assignable_roles_together_are_valid(self):
        """A list containing only assignable roles is valid."""
        roles = [
            Role.PRESCRIPTION_ANALYST.value,
            Role.CONFIG_MANAGER.value,
            Role.VIEWER.value,
        ]
        assert user_admin_service._has_valid_roles(roles) is True

    def test_empty_list_is_valid(self):
        """An empty role list is trivially valid."""
        assert user_admin_service._has_valid_roles([]) is True

    def test_unknown_role_is_invalid(self):
        """An unrecognized role name fails validation."""
        assert user_admin_service._has_valid_roles(["not-a-role"]) is False

    def test_special_non_assignable_role_is_invalid(self):
        """A non-assignable special role (e.g. ADMIN) is rejected."""
        assert user_admin_service._has_valid_roles([Role.ADMIN.value]) is False

    def test_mix_of_valid_and_invalid_is_invalid(self):
        """One invalid role makes the whole list invalid."""
        roles = [Role.VIEWER.value, "bogus"]
        assert user_admin_service._has_valid_roles(roles) is False


class TestHasValidFeatures:
    """Teste user_admin_service - _has_valid_features"""

    @pytest.mark.parametrize(
        "feature",
        [FeatureEnum.DISABLE_CPOE.value, FeatureEnum.STAGING_ACCESS.value],
    )
    def test_each_assignable_feature_is_valid(self, feature):
        """Each individually assignable feature passes validation."""
        assert user_admin_service._has_valid_features([feature]) is True

    def test_both_assignable_features_together_are_valid(self):
        """Both assignable features together are valid."""
        features = [
            FeatureEnum.DISABLE_CPOE.value,
            FeatureEnum.STAGING_ACCESS.value,
        ]
        assert user_admin_service._has_valid_features(features) is True

    def test_empty_list_is_valid(self):
        """An empty feature list is trivially valid."""
        assert user_admin_service._has_valid_features([]) is True

    def test_unknown_feature_is_invalid(self):
        """A feature outside the assignable set is rejected."""
        assert user_admin_service._has_valid_features(["SOME_OTHER_FEATURE"]) is False

    def test_non_assignable_known_feature_is_invalid(self):
        """A real FeatureEnum value that is not user-assignable is rejected."""
        assert (
            user_admin_service._has_valid_features([FeatureEnum.CONCILIATION.value])
            is False
        )
