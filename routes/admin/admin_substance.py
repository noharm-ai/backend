from flask import Blueprint

from decorators.api_endpoint_decorator import api_endpoint
from services.admin import admin_substance_service

app_admin_subs = Blueprint("app_admin_subs", __name__)


@app_admin_subs.route("/admin/substance/<int:id>", methods=["GET"])
@api_endpoint(is_admin=True)
def get_substance(id: int):
    return admin_substance_service.get_substance(substance_id=id)
