"""Unit tests for the RBAC role/permission resolution in security.role.Role.

These cover Role.get_permissions_from_user (how a user's configured role names
are turned into a flat permission list) and Role.get_special_roles (the set of
non-assignable roles). Both are pure functions with no database access.
"""

import pytest

from models.main import User
from security.permission import Permission
from security.role import Role


def _user_with_roles(roles):
    """Build an in-memory User whose config carries the given role names."""
    user = User()
    user.config = {"roles": roles}
    return user


class TestGetPermissionsFromUser:
    """Teste security.role - get_permissions_from_user"""

    def test_single_known_role_returns_its_permissions(self):
        """A user with one valid role gets exactly that role's permissions."""
        user = _user_with_roles([Role.SUPPORT_REQUESTER.value])

        result = Role.get_permissions_from_user(user)

        assert result == Role.SUPPORT_REQUESTER.permissions

    def test_role_name_is_case_insensitive(self):
        """Lower-case role names resolve the same as their canonical form."""
        user = _user_with_roles(["support_requester"])

        result = Role.get_permissions_from_user(user)

        assert result == Role.SUPPORT_REQUESTER.permissions

    def test_multiple_roles_concatenate_permissions(self):
        """Permissions from every valid role are combined into one list."""
        user = _user_with_roles(
            [Role.SUPPORT_REQUESTER.value, Role.VIEWER.value]
        )

        result = Role.get_permissions_from_user(user)

        expected = Role.SUPPORT_REQUESTER.permissions + Role.VIEWER.permissions
        assert result == expected

    def test_unknown_role_is_ignored(self):
        """An unrecognized role name contributes nothing and raises no error."""
        user = _user_with_roles(["NOT_A_REAL_ROLE"])

        assert Role.get_permissions_from_user(user) == []

    def test_known_and_unknown_roles_mixed(self):
        """Only the valid roles contribute; invalid ones are skipped."""
        user = _user_with_roles(
            ["NOT_A_REAL_ROLE", Role.SUPPORT_REQUESTER.value]
        )

        result = Role.get_permissions_from_user(user)

        assert result == Role.SUPPORT_REQUESTER.permissions

    def test_empty_roles_list_returns_empty(self):
        """A user with an empty roles list has no permissions."""
        assert Role.get_permissions_from_user(_user_with_roles([])) == []

    def test_config_without_roles_key_returns_empty(self):
        """A config dict lacking the 'roles' key yields no permissions."""
        user = User()
        user.config = {"features": []}

        assert Role.get_permissions_from_user(user) == []

    @pytest.mark.parametrize("config", [None, {}])
    def test_missing_or_empty_config_returns_empty(self, config):
        """A user with no usable config resolves to no permissions."""
        user = User()
        user.config = config

        assert Role.get_permissions_from_user(user) == []

    def test_result_contains_expected_permission(self):
        """Resolved permissions include the concrete Permission enum members."""
        user = _user_with_roles([Role.SUPPORT_REQUESTER.value])

        result = Role.get_permissions_from_user(user)

        assert Permission.READ_SUPPORT in result
        assert Permission.WRITE_SUPPORT in result


class TestCustomReportPermissions:
    """Teste security.role - which roles reach inactive custom reports"""

    def test_only_admin_and_curator_read_custom_reports(self):
        """READ_CUSTOM_REPORTS opens inactive custom reports, so it stays privileged.

        reports_custom_service._validate_report lets this permission past the
        "report is not active" check, so widening it to another role would also
        expose inactive reports to that role.
        """
        holders = {
            role.value for role in Role if Permission.READ_CUSTOM_REPORTS in role.permissions
        }

        assert holders == {Role.ADMIN.value, Role.CURATOR.value}

    def test_report_reader_roles_do_not_read_custom_reports(self):
        """The ordinary READ_REPORTS roles stay out of inactive custom reports."""
        for role in (
            Role.PRESCRIPTION_ANALYST,
            Role.VIEWER,
            Role.RESEARCHER,
            Role.TRAINING,
            Role.REGULATOR,
        ):
            assert Permission.READ_CUSTOM_REPORTS not in role.permissions
            assert Permission.WRITE_CUSTOM_REPORTS not in role.permissions


class TestGetSpecialRoles:
    """Teste security.role - get_special_roles (non-assignable roles)"""

    def test_returns_expected_role_values(self):
        """The special-role list matches the documented non-assignable set."""
        assert Role.get_special_roles() == [
            Role.ADMIN.value,
            Role.CURATOR.value,
            Role.ORGANIZATION_MANAGER.value,
            Role.STATIC_USER.value,
            Role.SERVICE_INTEGRATOR.value,
            Role.NAVIGATOR.value,
            Role.TRAINING.value,
        ]

    def test_assignable_role_is_not_special(self):
        """A regular assignable role is absent from the special list."""
        assert Role.SUPPORT_REQUESTER.value not in Role.get_special_roles()
