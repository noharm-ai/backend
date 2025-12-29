"""Route: tag related endpoints"""

from flask import Blueprint

from decorators.api_endpoint_decorator import api_endpoint
from services import queue_service

app_queue = Blueprint("app_queue", __name__)


@app_queue.route("/queue/status/<string:request_id>", methods=["GET"])
@api_endpoint()
def get_queue_status(request_id: str):
    """Get queue status"""
    return queue_service.check_sqs_message(request_id=request_id)
