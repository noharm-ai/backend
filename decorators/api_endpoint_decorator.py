import os
import logging
import inspect
from enum import Enum
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request
from functools import wraps

from models.main import db, dbSession, User
from utils import status
from services import permission_service

from exception.validation_error import ValidationError


class ApiEndpointUserGroup(Enum):
    ADMIN = "admin"
    MAINTAINER = "mantainer"
    PHARMA = "pharma"
    ALL = "all"


class ApiEndpointAction(Enum):
    READ = "read"
    WRITE = "write"


def api_endpoint(user_group: ApiEndpointUserGroup, action: ApiEndpointAction):

    def wrapper(f):
        @wraps(f)
        def decorator_f(*args, **kwargs):
            try:
                verify_jwt_in_request()

                user_context = User.find(get_jwt_identity())
                if "user_context" in inspect.signature(f).parameters:
                    kwargs["user_context"] = user_context

                dbSession.setSchema(user_context.schema)
                os.environ["TZ"] = "America/Sao_Paulo"

                if not _has_permission(
                    user_group=user_group, action=action, user_context=user_context
                ):
                    db.session.rollback()
                    db.session.close()
                    db.session.remove()

                    return {
                        "status": "error",
                        "message": "Usuário não autorizado",
                    }, status.HTTP_401_UNAUTHORIZED

                result = f(*args, **kwargs)

                db.session.commit()
                db.session.close()
                db.session.remove()

                return {"status": "success", "data": result}, status.HTTP_200_OK

            except ValidationError as e:
                db.session.rollback()
                db.session.close()
                db.session.remove()

                return {
                    "status": "error",
                    "message": str(e),
                    "code": e.code,
                }, e.httpStatus

            except Exception as e:
                db.session.rollback()
                db.session.close()
                db.session.remove()

                logging.basicConfig()
                logger = logging.getLogger("noharm.backend")
                logger.error(str(e))

                return {
                    "status": "error",
                    "message": str(e),
                }, status.HTTP_500_INTERNAL_SERVER_ERROR

        return decorator_f

    return wrapper


def _has_permission(
    user_group: ApiEndpointUserGroup, action: ApiEndpointAction, user_context: User
):
    # check params
    if not isinstance(user_group, ApiEndpointUserGroup):
        return False

    if not isinstance(action, ApiEndpointAction):
        return False

    # check permissions
    if action == ApiEndpointAction.WRITE:
        if permission_service.is_readonly(user_context):
            return False

    if user_group == ApiEndpointUserGroup.PHARMA and not permission_service.is_pharma(
        user_context
    ):
        return False

    if (
        user_group == ApiEndpointUserGroup.MAINTAINER
        and not permission_service.has_maintainer_permission(user_context)
    ):
        return False

    if user_group == ApiEndpointUserGroup.ADMIN and not permission_service.is_admin(
        user_context
    ):
        return False

    return True
