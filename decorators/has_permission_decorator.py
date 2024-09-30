import inspect
from typing import List
from functools import wraps
from flask import g
from flask_jwt_extended import get_jwt_identity

from models.main import User
from security.permission import Permission
from security.role import Role
from exception.authorization_error import AuthorizationError


def has_permission(*permissions: List[Permission]):

    def wrapper(f):
        @wraps(f)
        def decorator_f(*args, **kwargs):
            user_context = None

            if g.get("user_context", None) != None:
                user_context = g.get("user_context")
                roles = (
                    user_context.config["roles"]
                    if user_context.config and "roles" in user_context.config
                    else []
                )

                if len(roles) > 1 or roles[0] != Role.STATIC_USER.value:
                    raise AuthorizationError()
            else:
                if "user_context" in inspect.signature(f).parameters:
                    if "user_context" in kwargs and kwargs["user_context"] != None:
                        user_context = kwargs["user_context"]
                    else:
                        user_context = User.find(get_jwt_identity())
                        kwargs["user_context"] = user_context
                else:
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

            # inject extra params
            if "user_permissions" in inspect.signature(f).parameters:
                kwargs["user_permissions"] = user_permissions

            if g.get("permission_test_count", 0) == 0:
                if len(set.intersection(set(permissions), set(user_permissions))) == 0:
                    raise AuthorizationError()

            g.permission_test_count = g.get("permission_test_count", 0) + 1

            return f(*args, **kwargs)

        return decorator_f

    return wrapper
