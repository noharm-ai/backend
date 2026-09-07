"""Route: training related endpoints"""

from flask import Blueprint, request

from decorators.api_endpoint_decorator import api_endpoint
from exception.validation_error import ValidationError
from models.main import db
from models.requests.training_request import TrainingItemFinishRequest
from services import training_service
from utils import sessionutils

app_training = Blueprint("app_training", __name__)


@app_training.route("/training/list", methods=["GET"])
@api_endpoint(
    is_admin=True
)  # TODO: remove is_admin=True when the training is available to all users
def list_trainings():
    """List all active trainings"""
    return training_service.list_trainings()


@app_training.route("/training/overview", methods=["GET"])
@api_endpoint(
    is_admin=True
)  # TODO: remove is_admin=True when the training is available to all users
def get_training_overview():
    """Training progress of every user of the schema, for user managers"""
    return training_service.get_training_overview()


@app_training.route("/training/<int:id_training>/items", methods=["GET"])
@api_endpoint(
    is_admin=True
)  # TODO: remove is_admin=True when the training is available to all users
def list_training_items(id_training: int):
    """List all active items of a training"""
    return training_service.list_training_items(training_id=id_training)


@app_training.route("/training/<int:id_training>/certificate", methods=["GET"])
@api_endpoint(
    is_admin=True
)  # TODO: remove is_admin=True when the training is available to all users
def get_training_certificate(id_training: int):
    """Certificate data for a training module the current user finished"""
    return training_service.get_training_certificate(training_id=id_training)


@app_training.route("/training/item/<int:id_training_item>/finish", methods=["POST"])
@api_endpoint(
    is_admin=True
)  # TODO: remove is_admin=True when the training is available to all users
def finish_training_item(id_training_item: int):
    """Register that the current user finished a training item"""
    return training_service.finish_training_item(
        training_item_id=id_training_item,
        request_data=TrainingItemFinishRequest(**(request.get_json() or {})),
    )


@app_training.route("/public/certificate/<string:code>", methods=["GET"])
def validate_certificate(code: str):
    """PUBLIC - no authentication. Confirms a printed certificate is genuine.

    Deliberately not decorated with @api_endpoint: that decorator has no public
    mode, it always calls verify_jwt_in_request() and always demands that a
    permission check ran. This follows the /user/reset pattern instead. The
    /public/ prefix keeps "what is reachable anonymously" a one-line grep.
    """
    try:
        result = training_service.validate_certificate(validation_code=code)
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    # commits (a no-op for this read) and, more to the point, closes and removes
    # the session on an endpoint anyone can hit
    return sessionutils.tryCommit(db, result)
