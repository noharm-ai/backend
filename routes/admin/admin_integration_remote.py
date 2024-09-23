from flask import Blueprint, request

from decorators.api_endpoint_decorator import (
    api_endpoint,
    ApiEndpointUserGroup,
    ApiEndpointAction,
)
from models.main import User
from services.admin import (
    admin_integration_remote_service,
)

app_admin_integration_remote = Blueprint("app_admin_integration_remote", __name__)


@app_admin_integration_remote.route(
    "/admin/integration-remote/template", methods=["GET"]
)
@api_endpoint(user_group=ApiEndpointUserGroup.ADMIN, action=ApiEndpointAction.READ)
def get_template(user_context: User):
    return admin_integration_remote_service.get_template(
        user=user_context,
    )


@app_admin_integration_remote.route(
    "/admin/integration-remote/template-date", methods=["GET"]
)
@api_endpoint(user_group=ApiEndpointUserGroup.ADMIN, action=ApiEndpointAction.READ)
def get_template_date(user_context: User):
    return admin_integration_remote_service.get_template_date(
        user=user_context,
    )


@app_admin_integration_remote.route(
    "/admin/integration-remote/set-state", methods=["POST"]
)
@api_endpoint(user_group=ApiEndpointUserGroup.ADMIN, action=ApiEndpointAction.WRITE)
def set_state(user_context: User):
    request_data = request.get_json()

    return admin_integration_remote_service.set_state(
        id_processor=request_data.get("idProcessor", None),
        state=request_data.get("state", None),
        user=user_context,
    )


@app_admin_integration_remote.route(
    "/admin/integration-remote/queue-status", methods=["GET"]
)
@api_endpoint(user_group=ApiEndpointUserGroup.ADMIN, action=ApiEndpointAction.READ)
def queue_status(user_context: User):
    return admin_integration_remote_service.get_queue_status(
        id_queue_list=request.args.getlist("idQueueList[]"),
        user=user_context,
    )


@app_admin_integration_remote.route(
    "/admin/integration-remote/push-queue-request", methods=["POST"]
)
@api_endpoint(user_group=ApiEndpointUserGroup.ADMIN, action=ApiEndpointAction.WRITE)
def push_queue_request(user_context: User):
    request_data = request.get_json()

    return admin_integration_remote_service.push_queue_request(
        id_processor=request_data.get("idProcessor", None),
        action_type=request_data.get("actionType", None),
        data=request_data,
        user=user_context,
    )
