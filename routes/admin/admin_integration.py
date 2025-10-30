"""Route: admin integration related"""

from flask import Blueprint, request

from decorators.api_endpoint_decorator import api_endpoint
from services.admin import (
    admin_integration_service,
    admin_integration_status_service,
)
from models.requests.admin.admin_integration_request import (
    AdminIntegrationCreateSchemaRequest,
    AdminIntegrationUpsertGetnameRequest,
    AdminIntegrationUpsertSecurityGroupRequest,
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
        cpoe=request_data.get("cpoe", False),
        return_integration=request_data.get("returnIntegration", False),
        tp_prescalc=request_data.get("tpPrescalc", None),
    )


@app_admin_integration.route("/admin/integration/list", methods=["GET"])
@api_endpoint()
def list_integrations():
    return admin_integration_service.list_integrations()


@app_admin_integration.route("/admin/integration/create-schema", methods=["POST"])
@api_endpoint()
def create_schema():
    """create a new schema"""
    return admin_integration_service.create_schema(
        request_data=AdminIntegrationCreateSchemaRequest(**request.get_json())
    )


@app_admin_integration.route("/admin/integration/get-cloud-config", methods=["POST"])
@api_endpoint()
def get_cloud_config():
    """get cloud config"""
    request_data = request.get_json()
    return admin_integration_service.get_cloud_config(
        schema=request_data.get("schema", None)
    )


@app_admin_integration.route("/admin/integration/upsert-getname", methods=["POST"])
@api_endpoint()
def upsert_getname():
    """upsert getname config"""
    return admin_integration_service.upsert_getname(
        request_data=AdminIntegrationUpsertGetnameRequest(**request.get_json())
    )


@app_admin_integration.route(
    "/admin/integration/upsert-security-group", methods=["POST"]
)
@api_endpoint()
def upsert_security_group():
    """upsert sg config"""
    return admin_integration_service.upsert_security_group(
        request_data=AdminIntegrationUpsertSecurityGroupRequest(**request.get_json())
    )
