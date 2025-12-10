import inspect
import logging
import os
from functools import wraps

from flask import g, make_response, request
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request
from flask_jwt_extended.exceptions import JWTExtendedException
from jwt.exceptions import PyJWTError
from pydantic import ValidationError as PydanticValidationError

from exception.authorization_error import AuthorizationError
from exception.validation_error import ValidationError
from models.main import User, db, dbSession
from utils import status


def api_endpoint(download_headers=None):
    def wrapper(f):
        @wraps(f)
        def decorator_f(*args, **kwargs):
            user_context = None
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
                    raise AuthorizationError()

                db.session.commit()
                db.session.close()
                db.session.remove()

                # Handle download response with custom headers
                if download_headers:
                    response = make_response(result)
                    for header_name, header_value in download_headers.items():
                        response.headers[header_name] = header_value
                    return response

                return {"status": "success", "data": result}, status.HTTP_200_OK

            except (JWTExtendedException, PyJWTError):
                db.session.rollback()
                db.session.close()
                db.session.remove()

                logging.basicConfig()
                logger = logging.getLogger("noharm.backend")
                logger.warning(
                    "(%s) VALIDATION4xx: Login expirado",
                    user_context.schema if user_context else "undefined",
                )
                logger.warning(
                    "schema: %s", user_context.schema if user_context else "undefined"
                )

                return {
                    "status": "error",
                    "message": "Login expirado",
                    "code": "error.authorizationError",
                }, status.HTTP_401_UNAUTHORIZED

            except AuthorizationError:
                db.session.rollback()
                db.session.close()
                db.session.remove()

                logging.basicConfig()
                logger = logging.getLogger("noharm.backend")
                logger.warning(
                    "(%s) VALIDATION4xx: Usuário não autorizado no recurso",
                    user_context.schema if user_context else "undefined",
                )
                logger.warning(
                    "schema: %s", user_context.schema if user_context else "undefined"
                )

                return {
                    "status": "error",
                    "message": "Usuário não autorizado neste recurso",
                    "code": "error.authorizationError",
                }, status.HTTP_401_UNAUTHORIZED

            except ValidationError as e:
                db.session.rollback()
                db.session.close()
                db.session.remove()

                logging.basicConfig()
                logger = logging.getLogger("noharm.backend")
                logger.warning(
                    "(%s) VALIDATION4xx: %s",
                    user_context.schema if user_context else "undefined",
                    str(e),
                )
                logger.warning(
                    "schema: %s", user_context.schema if user_context else "undefined"
                )

                return {
                    "status": "error",
                    "message": str(e),
                    "code": e.code,
                }, e.httpStatus

            except PydanticValidationError as e:
                db.session.rollback()
                db.session.close()
                db.session.remove()

                logging.basicConfig()
                logger = logging.getLogger("noharm.backend")
                logger.warning(
                    "(%s) VALIDATION4xx: Parâmetros inválidos pydantic",
                    user_context.schema if user_context else "undefined",
                )
                logger.warning(
                    "schema: %s", user_context.schema if user_context else "undefined"
                )

                return {
                    "status": "error",
                    "message": "Parâmetros inválidos",
                    "code": 0,
                    "validations": e.errors(),
                }, status.HTTP_400_BAD_REQUEST

            except Exception as e:
                db.session.rollback()
                db.session.close()
                db.session.remove()

                logging.basicConfig()
                logger = logging.getLogger("noharm.backend")
                logger.exception(str(e))
                logger.error("Request data: %s", request.get_data())
                logger.error(
                    "error_schema: %s",
                    user_context.schema if user_context else "undefined",
                )

                return {
                    "status": "error",
                    "message": "Ocorreu um erro inesperado",
                }, status.HTTP_500_INTERNAL_SERVER_ERROR

        return decorator_f

    return wrapper
