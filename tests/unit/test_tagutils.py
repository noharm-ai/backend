"""Unit tests for utils.tagutils.filter_nav_tags.

filter_nav_tags hides ``NAVEGACAO_`` tags from users that lack the
READ_NAV permission. The permission list is read from the Flask request
global ``g``, so each test runs inside an application context with
``g.user_permissions`` set to the scenario under test.
"""

from contextlib import contextmanager

import pytest
from flask import g

from mobile import app
from security.permission import Permission
from utils import tagutils


@contextmanager
def _permissions(permissions):
    """Run inside an app context with the given user permissions on ``g``."""
    with app.app_context():
        if permissions is not None:
            g.user_permissions = permissions
        yield


def test_returns_all_tags_when_user_has_read_nav():
    """READ_NAV holders see every tag, including navigation ones."""
    tags = ["NAVEGACAO_A", "ALERGIA", "NAVEGACAO_B"]
    with _permissions([Permission.READ_NAV]):
        assert tagutils.filter_nav_tags(tags) == tags


def test_hides_navigation_tags_without_read_nav():
    """Without READ_NAV, NAVEGACAO_ prefixed tags are stripped out."""
    tags = ["NAVEGACAO_A", "ALERGIA", "NAVEGACAO_B", "PROTOCOLO"]
    with _permissions([Permission.READ_PRESCRIPTION]):
        assert tagutils.filter_nav_tags(tags) == ["ALERGIA", "PROTOCOLO"]


def test_hides_navigation_tags_when_no_permissions_set():
    """With no permissions on g, navigation tags are still hidden."""
    tags = ["NAVEGACAO_A", "ALERGIA"]
    with _permissions(None):
        assert tagutils.filter_nav_tags(tags) == ["ALERGIA"]


def test_non_navigation_tags_are_untouched():
    """A list without navigation tags is returned unchanged."""
    tags = ["ALERGIA", "PROTOCOLO", "OUTRO"]
    with _permissions([]):
        assert tagutils.filter_nav_tags(tags) == tags


@pytest.mark.parametrize("empty", [[], None])
def test_empty_input_returned_as_is(empty):
    """Empty or None input short-circuits and is returned unchanged."""
    with _permissions([]):
        assert tagutils.filter_nav_tags(empty) == empty
