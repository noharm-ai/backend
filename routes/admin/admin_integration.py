"""Route: admin integration related"""

from flask import Blueprint

from decorators.api_endpoint_decorator import api_endpoint
from services.admin import admin_integration_service

app_admin_integration = Blueprint("app_admin_integration", __name__)


@app_admin_integration.route(
    "/admin/integration/update-user-security-group", methods=["POST"]
)
@api_endpoint(is_admin=True)
def update_user_security_group():
    """update user sg rules"""

    return admin_integration_service.update_user_security_group()
