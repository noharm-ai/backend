"""Unit tests for decorators.has_permission_decorator.has_permission.

``@has_permission(*permissions)`` is the authorization gate on every service
function. It resolves the caller, expands their roles into permissions, and
lets the call through only if the caller holds at least one of the listed
permissions. It also feeds the service: ``user_context`` and
``user_permissions`` are injected when the function declares them, and the
caller's permissions and features are published on ``flask.g``.

The caller comes from one of three places:

* ``g.user_context`` — a pre-authenticated context, accepted only when it is a
  lone ``STATIC_USER``;
* an explicit ``user_context`` keyword argument, when the function declares
  that parameter;
* otherwise the JWT identity, looked up through ``User.find``.

Only the *first* decorated call of a request is checked: ``g`` counts the
checks in ``permission_test_count`` and nested services skip the test once
the outer one passed. ``api_endpoint`` relies on that same counter to refuse
routes whose service has no ``@has_permission`` at all.

The JWT lookup and the ``User`` model are patched, so no token or database is
involved; each test runs in its own Flask request context so ``g`` starts
empty.
"""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from flask import g

from decorators.has_permission_decorator import has_permission
from exception.authorization_error import AuthorizationError
from mobile import app
from security.permission import Permission
from security.role import Role

JWT_IDENTITY = "42"


def _user(roles, features=None, user_id=42):
    """Build a fake user carrying ``roles`` (and ``features``) in its config."""
    config = {"roles": roles}
    if features is not None:
        config["features"] = features
    return SimpleNamespace(id=user_id, schema="demo", config=config)


@contextmanager
def request_as(user):
    """Run the block in a fresh request whose JWT resolves to ``user``.

    Yields the patched ``User`` class so tests can assert whether the JWT
    lookup happened.
    """
    with app.test_request_context():
        with (
            patch(
                "decorators.has_permission_decorator.get_jwt_identity",
                return_value=JWT_IDENTITY,
            ),
            patch("decorators.has_permission_decorator.User") as mock_user_cls,
        ):
            mock_user_cls.find.return_value = user
            yield mock_user_cls


# --- the permission check ------------------------------------------------------


def test_caller_with_permission_is_let_through():
    """A role granting the listed permission runs the function and returns its result."""

    @has_permission(Permission.READ_PRESCRIPTION)
    def service(value):
        """Echo the argument."""
        return value * 2

    with request_as(_user([Role.PRESCRIPTION_ANALYST.value])) as mock_user_cls:
        assert service(21) == 42

    mock_user_cls.find.assert_called_once_with(JWT_IDENTITY)


def test_caller_without_permission_is_refused_before_running():
    """Lacking every listed permission raises and the function body never runs."""
    calls = []

    @has_permission(Permission.ADMIN_DRUGS)
    def service():
        """Record that the body ran."""
        calls.append(True)

    with request_as(_user([Role.PRESCRIPTION_ANALYST.value])):
        with pytest.raises(AuthorizationError):
            service()

    assert calls == []


def test_any_listed_permission_is_enough():
    """The listed permissions are alternatives: holding one of them suffices."""

    @has_permission(Permission.ADMIN_DRUGS, Permission.READ_REPORTS)
    def service():
        """Return a marker."""
        return "ok"

    with request_as(_user([Role.PRESCRIPTION_ANALYST.value])):
        assert service() == "ok"


def test_unknown_jwt_user_is_refused():
    """A token whose identity no longer resolves to a user is refused."""

    @has_permission(Permission.READ_PRESCRIPTION)
    def service():
        """Never reached."""
        return "ok"

    with request_as(None):
        with pytest.raises(AuthorizationError):
            service()


@pytest.mark.parametrize(
    "config",
    [None, {}, {"roles": []}, {"roles": ["NOT_A_ROLE"]}],
    ids=["no-config", "empty-config", "no-roles", "unknown-role"],
)
def test_user_without_valid_roles_is_refused(config):
    """No roles, or only unknown ones, grant nothing."""

    @has_permission(Permission.READ_PRESCRIPTION)
    def service():
        """Never reached."""
        return "ok"

    user = SimpleNamespace(id=42, schema="demo", config=config)

    with request_as(user):
        with pytest.raises(AuthorizationError):
            service()


def test_role_names_are_case_insensitive():
    """Roles stored in lower case still expand into their permissions."""

    @has_permission(Permission.READ_PRESCRIPTION)
    def service():
        """Return a marker."""
        return "ok"

    with request_as(_user([Role.PRESCRIPTION_ANALYST.value.lower()])):
        assert service() == "ok"


# --- what the service receives ------------------------------------------------


def test_user_permissions_are_injected_when_declared():
    """A ``user_permissions`` parameter receives the caller's expanded permissions."""

    @has_permission(Permission.READ_PRESCRIPTION)
    def service(user_permissions: list[Permission]):
        """Return the injected permissions."""
        return user_permissions

    with request_as(_user([Role.PRESCRIPTION_ANALYST.value, Role.VIEWER.value])):
        permissions = service()

    assert permissions == (
        Role.PRESCRIPTION_ANALYST.permissions + Role.VIEWER.permissions
    )


def test_nothing_is_injected_into_a_plain_function():
    """A function declaring neither parameter is called with its own args only."""

    @has_permission(Permission.READ_PRESCRIPTION)
    def service(*args, **kwargs):
        """Return what was received."""
        return args, kwargs

    with request_as(_user([Role.PRESCRIPTION_ANALYST.value])):
        assert service(1, flag=True) == ((1,), {"flag": True})


def test_user_context_is_resolved_from_jwt_and_injected():
    """A declared ``user_context`` without a value is filled with the JWT user."""
    user = _user([Role.PRESCRIPTION_ANALYST.value])

    @has_permission(Permission.READ_PRESCRIPTION)
    def service(user_context=None):
        """Return the injected user."""
        return user_context

    with request_as(user):
        assert service() is user


def test_explicit_none_user_context_falls_back_to_jwt():
    """Passing ``user_context=None`` is the same as not passing it."""
    user = _user([Role.PRESCRIPTION_ANALYST.value])

    @has_permission(Permission.READ_PRESCRIPTION)
    def service(user_context=None):
        """Return the injected user."""
        return user_context

    with request_as(user) as mock_user_cls:
        assert service(user_context=None) is user

    mock_user_cls.find.assert_called_once_with(JWT_IDENTITY)


def test_explicit_user_context_is_trusted_without_jwt_lookup():
    """A caller-supplied ``user_context`` is the one checked; the JWT isn't read."""
    caller = _user([Role.PRESCRIPTION_ANALYST.value], user_id=7)

    @has_permission(Permission.READ_PRESCRIPTION)
    def service(user_context=None):
        """Return the user the service saw."""
        return user_context

    with request_as(_user([])) as mock_user_cls:
        assert service(user_context=caller) is caller

    mock_user_cls.find.assert_not_called()


def test_explicit_user_context_is_still_checked():
    """A supplied ``user_context`` lacking the permission is refused."""

    @has_permission(Permission.ADMIN_DRUGS)
    def service(user_context=None):
        """Never reached."""
        return user_context

    with request_as(_user([Role.ADMIN.value])):
        with pytest.raises(AuthorizationError):
            service(user_context=_user([Role.VIEWER.value]))


def test_permissions_and_features_are_published_on_g():
    """``g`` carries the caller's permissions and features for later checks."""
    user = _user([Role.PRESCRIPTION_ANALYST.value], features=["FEATURE_A"])

    @has_permission(Permission.READ_PRESCRIPTION)
    def service():
        """Read back what the decorator stored on ``g``."""
        return g.user_permissions, g.user_features

    with request_as(user):
        permissions, features = service()

    assert permissions == Role.PRESCRIPTION_ANALYST.permissions
    assert features == ["FEATURE_A"]


def test_features_default_to_empty_list():
    """A user config without ``features`` publishes an empty list."""

    @has_permission(Permission.READ_PRESCRIPTION)
    def service():
        """Read back the published features."""
        return g.user_features

    with request_as(_user([Role.PRESCRIPTION_ANALYST.value])):
        assert service() == []


# --- one check per request -----------------------------------------------------


def test_each_decorated_call_bumps_the_check_counter():
    """``permission_test_count`` grows per decorated call, as ``api_endpoint`` expects."""

    @has_permission(Permission.READ_PRESCRIPTION)
    def service():
        """Read the counter as seen inside the service."""
        return g.permission_test_count

    with request_as(_user([Role.PRESCRIPTION_ANALYST.value])):
        assert g.get("permission_test_count", 0) == 0
        assert service() == 1
        assert service() == 2
        assert g.permission_test_count == 2


def test_failed_check_does_not_bump_the_counter():
    """A refused call leaves the counter at zero, so the route can't look checked."""

    @has_permission(Permission.ADMIN_DRUGS)
    def service():
        """Never reached."""

    with request_as(_user([Role.VIEWER.value])):
        with pytest.raises(AuthorizationError):
            service()

        assert g.get("permission_test_count", 0) == 0


def test_nested_service_is_not_rechecked():
    """Once the outer service passed, inner services skip the permission test."""

    @has_permission(Permission.ADMIN_DRUGS)
    def inner():
        """Requires a permission the caller doesn't hold."""
        return "inner ran"

    @has_permission(Permission.READ_PRESCRIPTION)
    def outer():
        """Calls the inner service."""
        return inner()

    with request_as(_user([Role.PRESCRIPTION_ANALYST.value])):
        assert outer() == "inner ran"
        assert g.permission_test_count == 2


def test_first_call_of_a_request_is_always_checked():
    """Calling the stricter service first is still refused."""

    @has_permission(Permission.ADMIN_DRUGS)
    def strict():
        """Never reached."""

    with request_as(_user([Role.PRESCRIPTION_ANALYST.value])):
        with pytest.raises(AuthorizationError):
            strict()


# --- pre-authenticated context on g -------------------------------------------


def test_static_user_on_g_is_used_without_jwt_lookup():
    """A lone STATIC_USER on ``g.user_context`` is the caller; the JWT isn't read."""
    static_user = _user([Role.STATIC_USER.value], user_id=0)

    @has_permission(Permission.READ_STATIC)
    def service(user_permissions: list[Permission]):
        """Return the injected permissions."""
        return user_permissions

    with request_as(_user([Role.ADMIN.value])) as mock_user_cls:
        g.user_context = static_user
        assert service() == Role.STATIC_USER.permissions

    mock_user_cls.find.assert_not_called()


def test_static_user_on_g_is_still_checked():
    """STATIC_USER only holds the static permissions."""

    @has_permission(Permission.READ_PRESCRIPTION)
    def service():
        """Never reached."""

    with request_as(_user([Role.ADMIN.value])):
        g.user_context = _user([Role.STATIC_USER.value], user_id=0)
        with pytest.raises(AuthorizationError):
            service()


@pytest.mark.parametrize(
    "roles",
    [
        [Role.ADMIN.value],
        [Role.STATIC_USER.value, Role.ADMIN.value],
        [Role.ADMIN.value, Role.STATIC_USER.value],
    ],
    ids=["other-role", "static-plus-admin", "admin-plus-static"],
)
def test_non_static_context_on_g_is_refused(roles):
    """``g.user_context`` is reserved to a lone STATIC_USER, whatever it holds."""

    @has_permission(Permission.READ_STATIC, Permission.ADMIN_DRUGS)
    def service():
        """Never reached."""

    with request_as(_user([Role.ADMIN.value])):
        g.user_context = _user(roles)
        with pytest.raises(AuthorizationError):
            service()
