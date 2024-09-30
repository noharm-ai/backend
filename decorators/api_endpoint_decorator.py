import os
import logging
import inspect
from flask import g
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request
from functools import wraps

from models.main import db, dbSession, User
from utils import status

from exception.validation_error import ValidationError
from exception.authorization_error import AuthorizationError


def api_endpoint():

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

                result = f(*args, **kwargs)

                # should check for permission at least once
                if g.get("permission_test_count", 0) == 0:
                    print("sshould check for permission at least once")
                    raise AuthorizationError()

                db.session.commit()
                db.session.close()
                db.session.remove()

                return {"status": "success", "data": result}, status.HTTP_200_OK

            except AuthorizationError as e:
                db.session.rollback()
                db.session.close()
                db.session.remove()

                return {
                    "status": "error",
                    "message": "Usuário não autorizado neste recurso",
                    "code": "error.authorizationError",
                }, status.HTTP_401_UNAUTHORIZED

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
                    "message": "Ocorreu um erro inesperado",
                }, status.HTTP_500_INTERNAL_SERVER_ERROR

        return decorator_f

    return wrapper
