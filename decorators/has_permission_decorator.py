import inspect
from typing import List
from functools import wraps
from flask_jwt_extended import get_jwt_identity

from models.main import User
from security.permission import Permission
from security.role import Role
from exception.authorization_error import AuthorizationError


def has_permission(*permissions: List[Permission]):

    def wrapper(f):
        @wraps(f)
        def decorator_f(*args, **kwargs):
            user_context = User.find(get_jwt_identity())

            if user_context == None:
                raise AuthorizationError()

            roles = (
                user_context.config["roles"]
                if user_context.config and "roles" in user_context.config
                else []
            )
            user_permissions = []
            for r in roles:
                try:
                    role = Role(str(r).upper())
                    user_permissions = user_permissions + role.permissions
                except:
                    pass

            if len(set.intersection(set(permissions), set(user_permissions))) == 0:
                raise AuthorizationError()

            # inject params
            if "user_context" in inspect.signature(f).parameters:
                kwargs["user_context"] = user_context
            if "user_permissions" in inspect.signature(f).parameters:
                kwargs["user_permissions"] = user_permissions

            return f(*args, **kwargs)

        return decorator_f

    return wrapper
