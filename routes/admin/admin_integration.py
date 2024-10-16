from flask import Blueprint, request

from decorators.api_endpoint_decorator import api_endpoint
from services.admin import (
    admin_integration_service,
    admin_integration_status_service,
)

app_admin_integration = Blueprint("app_admin_integration", __name__)


@app_admin_integration.route("/admin/integration/refresh-agg", methods=["POST"])
@api_endpoint()
def refresh_agg():
    result = admin_integration_service.refresh_agg()

    return result.rowcount


@app_admin_integration.route(
    "/admin/integration/refresh-prescription", methods=["POST"]
)
@api_endpoint()
def refresh_prescriptions():
    result = admin_integration_service.refresh_prescriptions()

    return result.rowcount


@app_admin_integration.route(
    "/admin/integration/init-intervention-reason", methods=["POST"]
)
@api_endpoint()
def init_intervention_reason():
    result = admin_integration_service.init_intervention_reason()

    return result.rowcount


@app_admin_integration.route("/admin/integration/status", methods=["GET"])
@api_endpoint()
def get_status():
    return admin_integration_status_service.get_status()


@app_admin_integration.route("/admin/integration/update", methods=["POST"])
@api_endpoint()
def update_config():
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
    )


@app_admin_integration.route("/admin/integration/list", methods=["GET"])
@api_endpoint()
def list_integrations():
    return admin_integration_service.list_integrations()
