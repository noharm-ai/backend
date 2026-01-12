from flask import Blueprint, request

from decorators.api_endpoint_decorator import api_endpoint
from services.admin import admin_intervention_reason_service

app_admin_interv = Blueprint("app_admin_interv", __name__)


@app_admin_interv.route("/admin/intervention-reason", methods=["GET"])
@api_endpoint(is_admin=True)
def get_records():
    list = admin_intervention_reason_service.get_reasons()

    return admin_intervention_reason_service.list_to_dto(list)


@app_admin_interv.route("/admin/intervention-reason", methods=["POST"])
@api_endpoint(is_admin=True)
def upsert_record():
    data = request.get_json()

    reason = admin_intervention_reason_service.upsert_reason(
        data.get("id", None),
        admin_intervention_reason_service.data_to_object(data),
    )

    return admin_intervention_reason_service.list_to_dto(reason)
