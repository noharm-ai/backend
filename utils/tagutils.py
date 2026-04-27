"""Utilities for patient tag operations."""

from flask import g

from security.permission import Permission


def filter_nav_tags(tags: list) -> list:
    """Hides NAVEGACAO_ tags from users without READ_NAV permission."""
    if not tags:
        return tags
    user_permissions = g.get("user_permissions", [])
    if Permission.READ_NAV in user_permissions:
        return tags
    return [t for t in tags if not t.startswith("NAVEGACAO_")]
