"""Route: getname validation page (public)"""

from functools import wraps

from flask import Blueprint, request
from pydantic import ValidationError as PydanticValidationError

from exception.validation_error import ValidationError
from models.main import db
from models.requests.getname_validation_request import GetnameValidationResultRequest
from services import getname_validation_service
from utils import logger, sessionutils, status

app_getname_validation = Blueprint("app_getname_validation", __name__)


def _public_endpoint(f):
    """PUBLIC - no authentication: the link token in the path is the credential.

    Not @api_endpoint: that decorator has no public mode, it always verifies a
    JWT and demands that a permission check ran. This follows the
    /public/certificate pattern, and the /public/ prefix keeps "what is
    reachable anonymously" a one-line grep.
    """

    @wraps(f)
    def decorated(*args, **kwargs):
        try:
            result = f(*args, **kwargs)
        except ValidationError as e:
            _discard_session()
            return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus
        except PydanticValidationError:
            _discard_session()
            return {
                "status": "error",
                "message": "Parâmetros inválidos",
            }, status.HTTP_400_BAD_REQUEST
        except Exception as e:  # pylint: disable=broad-exception-caught
            _discard_session()
            logger.backend_logger.exception(str(e))
            return {
                "status": "error",
                "message": "Ocorreu um erro inesperado",
            }, status.HTTP_500_INTERNAL_SERVER_ERROR

        # commits and, on an endpoint anyone can hit, closes and removes the session
        return sessionutils.tryCommit(db, result)

    return decorated


def _discard_session():
    """Roll back and release the session of a request that failed"""
    db.session.rollback()
    db.session.close()
    db.session.remove()


@app_getname_validation.route(
    "/public/getname-validation/<string:token>", methods=["GET"]
)
@_public_endpoint
def get_validation(token: str):
    """What the validation link tests"""
    return getname_validation_service.get_validation(token=token)


@app_getname_validation.route(
    "/public/getname-validation/<string:token>/auth-token", methods=["POST"]
)
@_public_endpoint
def get_auth_token(token: str):
    """Getname token for the lookup step of the test"""
    return getname_validation_service.get_auth_token(token=token)


@app_getname_validation.route(
    "/public/getname-validation/<string:token>/result", methods=["POST"]
)
@_public_endpoint
def save_result(token: str):
    """Save the receipt of a run and register it on the support ticket"""
    return getname_validation_service.save_result(
        token=token,
        request_data=GetnameValidationResultRequest(
            **(request.get_json(silent=True) or {})
        ),
    )
