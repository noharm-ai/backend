"""Route: admin integration related"""

from flask import Blueprint, request

from decorators.api_endpoint_decorator import api_endpoint
from services.admin import admin_integration_service

app_admin_integration = Blueprint("app_admin_integration", __name__)


@app_admin_integration.route(
    "/admin/integration/init-intervention-reason", methods=["POST"]
)
@api_endpoint(is_admin=True)
def init_intervention_reason():
    result = admin_integration_service.init_intervention_reason()

    return result.rowcount
