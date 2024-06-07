from models.enums import RoleEnum
from models.main import User


def is_admin(user):
    user_roles = set(_get_roles(user))

    return RoleEnum.ADMIN.value in user_roles


def has_maintainer_permission(user):
    return has_any_role(user, RoleEnum.ADMIN.value, RoleEnum.TRAINING.value)


def is_pharma(user):
    return not has_any_role(
        user,
        RoleEnum.ADMIN.value,
        RoleEnum.TRAINING.value,
        RoleEnum.SUPPORT.value,
        RoleEnum.READONLY.value,
    )


def is_user_admin(user: User):
    return not has_any_role(user, RoleEnum.USER_ADMIN)


def is_cpoe(user):
    return has_any_role(user, RoleEnum.CPOE.value)


def has_any_role(user, *roles):
    user_roles = set(_get_roles(user))

    return len(user_roles.intersection(roles)) > 0


def _get_roles(user):
    return user.config["roles"] if user.config and "roles" in user.config else []
