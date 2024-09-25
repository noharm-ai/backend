from flask import Blueprint, request

from decorators.api_endpoint_decorator import api_endpoint
from services.admin import (
    admin_integration_remote_service,
)

app_admin_integration_remote = Blueprint("app_admin_integration_remote", __name__)


@app_admin_integration_remote.route(
    "/admin/integration-remote/template", methods=["GET"]
)
@api_endpoint()
def get_template():
    return admin_integration_remote_service.get_template()


@app_admin_integration_remote.route(
    "/admin/integration-remote/template-date", methods=["GET"]
)
@api_endpoint()
def get_template_date():
    return admin_integration_remote_service.get_template_date()


@app_admin_integration_remote.route(
    "/admin/integration-remote/queue-status", methods=["GET"]
)
@api_endpoint()
def queue_status():
    return admin_integration_remote_service.get_queue_status(
        id_queue_list=request.args.getlist("idQueueList[]"),
    )


@app_admin_integration_remote.route(
    "/admin/integration-remote/push-queue-request", methods=["POST"]
)
@api_endpoint()
def push_queue_request():
    request_data = request.get_json()

    return admin_integration_remote_service.push_queue_request(
        id_processor=request_data.get("idProcessor", None),
        action_type=request_data.get("actionType", None),
        data=request_data,
    )
