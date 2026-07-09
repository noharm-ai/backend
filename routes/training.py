"""Route: training related endpoints"""

from flask import Blueprint

from services import training_service
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
