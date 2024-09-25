import inspect
from functools import wraps
from flask_jwt_extended import get_jwt_identity

from models.main import User
from security.permission import Permission
from security.role import Role
from exception.authorization_error import AuthorizationError


def has_permission(permission: Permission):

    def wrapper(f):
        @wraps(f)
        def decorator_f(*args, **kwargs):
            user_context = User.find(get_jwt_identity())
            if "user_context" in inspect.signature(f).parameters:
                kwargs["user_context"] = user_context

            roles = (
                user_context.config["roles"]
                if user_context.config and "roles" in user_context.config
                else []
            )
            user_permissions = []
            for r in roles:
                try:
                    role = Role(str(r).upper())
                    print("role", role)
                    user_permissions = user_permissions + role.permissions
                except:
                    pass

            print("permisisons", user_permissions)

            if permission not in user_permissions:
                raise AuthorizationError()

            return f(*args, **kwargs)

        return decorator_f

    return wrapper
