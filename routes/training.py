"""Route: training related endpoints"""

from flask import Blueprint, request

from services import training_service
from models.requests.training_request import TrainingItemFinishRequest
from decorators.api_endpoint_decorator import api_endpoint

app_training = Blueprint("app_training", __name__)


@app_training.route("/training/list", methods=["GET"])
@api_endpoint()
def list_trainings():
    """List all active trainings"""
    return training_service.list_trainings()


@app_training.route("/training/<int:id_training>/items", methods=["GET"])
@api_endpoint()
def list_training_items(id_training: int):
    """List all active items of a training"""
    return training_service.list_training_items(training_id=id_training)


@app_training.route("/training/item/<int:id_training_item>/finish", methods=["POST"])
@api_endpoint()
def finish_training_item(id_training_item: int):
    """Register that the current user finished a training item"""
    return training_service.finish_training_item(
        training_item_id=id_training_item,
        request_data=TrainingItemFinishRequest(**(request.get_json() or {})),
    )
