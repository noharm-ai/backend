import os
import logging
from enum import Enum
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request
from functools import wraps

from models.main import db, dbSession, User
from utils import status
from services import permission_service

from exception.validation_error import ValidationError


class ApiEndpointType(Enum):
    ADMIN = "admin"
    MAINTAINER = "mantainer"
    USER = "user"


def api_endpoint(api_endpoint_type: ApiEndpointType):

    def wrapper(f):
        @wraps(f)
        def decorator_f(*args, **kwargs):
            try:
                verify_jwt_in_request()

                user_context = User.find(get_jwt_identity())
                kwargs["user_context"] = user_context

                dbSession.setSchema(user_context.schema)
                os.environ["TZ"] = "America/Sao_Paulo"

                has_permission = False

                if (
                    api_endpoint_type == ApiEndpointType.USER
                    and permission_service.is_pharma(user_context)
                ):
                    has_permission = True
                elif (
                    api_endpoint_type == ApiEndpointType.MAINTAINER
                    and permission_service.has_maintainer_permission(user_context)
                ):
                    has_permission = True
                elif (
                    api_endpoint_type == ApiEndpointType.ADMIN
                    and permission_service.is_admin(user_context)
                ):
                    has_permission = True

                if not has_permission or permission_service.is_readonly(user_context):
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
