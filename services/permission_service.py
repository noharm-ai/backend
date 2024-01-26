from typing import List

from models.enums import RoleEnum


def has_maintainer_permission(user):
    return has_any_role(user, RoleEnum.ADMIN.value, RoleEnum.TRAINING.value)


def has_any_role(user, *roles):
    user_roles = set(_get_roles(user))

    return len(user_roles.intersection(roles)) > 0


def _get_roles(user):
    return user.config["roles"] if user.config and "roles" in user.config else []
