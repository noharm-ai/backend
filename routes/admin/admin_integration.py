"""Route: admin integration related"""

from flask import Blueprint, request

from decorators.api_endpoint_decorator import api_endpoint
from models.requests.admin.admin_integration_request import (
    AdminIntegrationCreateSchemaRequest,
    AdminIntegrationUpsertGetnameRequest,
    AdminIntegrationUpsertSecurityGroupRequest,
)
from services.admin import (
    admin_integration_service,
    admin_integration_status_service,
)

app_admin_integration = Blueprint("app_admin_integration", __name__)


@app_admin_integration.route(
    "/admin/integration/refresh-prescription", methods=["POST"]
)
@api_endpoint(is_admin=True)
def refresh_prescriptions():
    result = admin_integration_service.refresh_prescriptions()

    return result.rowcount


@app_admin_integration.route(
    "/admin/integration/init-intervention-reason", methods=["POST"]
)
@api_endpoint(is_admin=True)
def init_intervention_reason():
    result = admin_integration_service.init_intervention_reason()

    return result.rowcount


@app_admin_integration.route("/admin/integration/status", methods=["GET"])
@api_endpoint(is_admin=True)
def get_status():
    return admin_integration_status_service.get_status()


@app_admin_integration.route("/admin/integration/update", methods=["POST"])
@api_endpoint(is_admin=True)
def update_config():
    request_data = request.get_json()

    return admin_integration_service.update_integration_config(
        schema=request_data.get("schema", None),
        status=request_data.get("status", None),
        nh_care=request_data.get("nhCare", None),
        config=request_data.get("config", None),
        return_integration=request_data.get("returnIntegration", False),
        tp_prescalc=request_data.get("tpPrescalc", None),
        tp_pep=request_data.get("tp_pep", None),
    )


@app_admin_integration.route("/admin/integration/list", methods=["GET"])
@api_endpoint(is_admin=True)
def list_integrations():
    return admin_integration_service.list_integrations()


@app_admin_integration.route("/admin/integration/create-schema", methods=["POST"])
@api_endpoint(is_admin=True)
def create_schema():
    """create a new schema"""
    return admin_integration_service.create_schema(
        request_data=AdminIntegrationCreateSchemaRequest(**request.get_json())
    )


@app_admin_integration.route("/admin/integration/template-list", methods=["GET"])
@api_endpoint(is_admin=True)
def get_template_list():
    """get template list with dates"""
    return admin_integration_service.get_template_list()


@app_admin_integration.route("/admin/integration/get-cloud-config", methods=["POST"])
@api_endpoint(is_admin=True)
def get_cloud_config():
    """get cloud config"""
    request_data = request.get_json()
    return admin_integration_service.get_cloud_config(
        schema=request_data.get("schema", None)
    )


@app_admin_integration.route("/admin/integration/upsert-getname", methods=["POST"])
@api_endpoint(is_admin=True)
def upsert_getname():
    """upsert getname config"""
    return admin_integration_service.upsert_getname(
        request_data=AdminIntegrationUpsertGetnameRequest(**request.get_json())
    )


@app_admin_integration.route(
    "/admin/integration/upsert-security-group", methods=["POST"]
)
@api_endpoint(is_admin=True)
def upsert_security_group():
    """upsert sg config"""
    return admin_integration_service.upsert_security_group(
        request_data=AdminIntegrationUpsertSecurityGroupRequest(**request.get_json())
    )


@app_admin_integration.route(
    "/admin/integration/update-user-security-group", methods=["POST"]
)
@api_endpoint(is_admin=True)
def update_user_security_group():
    """update user sg rules"""

    return admin_integration_service.update_user_security_group()
