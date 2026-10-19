from flask import Blueprint, request

from decorators.api_endpoint_decorator import api_endpoint
from services.admin import admin_drug_service

app_admin_drug = Blueprint("app_admin_drug", __name__)


@app_admin_drug.route("/admin/drug/ref", methods=["GET"])
@api_endpoint(is_admin=True)
def get_drug_ref():
    sctid = request.args.get("sctid", None)

    return admin_drug_service.get_drug_ref(sctid=sctid)
