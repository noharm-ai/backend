from flask import Blueprint, request

from decorators.api_endpoint_decorator import (
    api_endpoint,
    ApiEndpointUserGroup,
    ApiEndpointAction,
)
from models.main import User
from services.admin import (
    admin_integration_service,
    admin_integration_status_service,
)

app_admin_integration = Blueprint("app_admin_integration", __name__)


@app_admin_integration.route("/admin/integration/refresh-agg", methods=["POST"])
@api_endpoint(
    user_group=ApiEndpointUserGroup.MAINTAINER, action=ApiEndpointAction.WRITE
)
def refresh_agg(user_context: User):
    result = admin_integration_service.refresh_agg(
        user=user_context,
    )

    return result.rowcount


@app_admin_integration.route(
    "/admin/integration/refresh-prescription", methods=["POST"]
)
@api_endpoint(user_group=ApiEndpointUserGroup.ADMIN, action=ApiEndpointAction.WRITE)
def refresh_prescriptions(user_context: User):
    result = admin_integration_service.refresh_prescriptions(
        user=user_context,
    )

    return result.rowcount


@app_admin_integration.route(
    "/admin/integration/init-intervention-reason", methods=["POST"]
)
@api_endpoint(
    user_group=ApiEndpointUserGroup.MAINTAINER, action=ApiEndpointAction.WRITE
)
def init_intervention_reason(user_context: User):
    result = admin_integration_service.init_intervention_reason(
        user=user_context,
    )

    return result.rowcount


@app_admin_integration.route("/admin/integration/status", methods=["GET"])
@api_endpoint(user_group=ApiEndpointUserGroup.MAINTAINER, action=ApiEndpointAction.READ)
def get_status(user_context: User):
    return admin_integration_status_service.get_status(
        user=user_context,
    )


@app_admin_integration.route("/admin/integration/update", methods=["POST"])
@api_endpoint(user_group=ApiEndpointUserGroup.ADMIN, action=ApiEndpointAction.WRITE)
def update_config(user_context: User):
    request_data = request.get_json()

    return admin_integration_service.update_integration_config(
        schema=request_data.get("schema", None),
        status=request_data.get("status", None),
        nh_care=request_data.get("nhCare", None),
        config=request_data.get("config", None),
        fl1=request_data.get("fl1", None),
        fl2=request_data.get("fl2", None),
        fl3=request_data.get("fl3", None),
        fl4=request_data.get("fl4", None),
        user=user_context,
    )


@app_admin_integration.route("/admin/integration/list", methods=["GET"])
@api_endpoint(user_group=ApiEndpointUserGroup.ADMIN, action=ApiEndpointAction.READ)
def list_integrations(user_context: User):
    return admin_integration_service.list_integrations(
        user=user_context,
    )
