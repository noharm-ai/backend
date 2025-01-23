from flask import Blueprint, request

from services.admin import admin_substance_service
from decorators.api_endpoint_decorator import api_endpoint
from models.requests.admin.admin_substance import AdminSubstanceRequest

app_admin_subs = Blueprint("app_admin_subs", __name__)


@app_admin_subs.route("/admin/substance/list", methods=["POST"])
@api_endpoint()
def get_substances():
    data = request.get_json()

    list = admin_substance_service.get_substances(
        limit=data.get("limit", 50),
        offset=data.get("offset", 0),
        name=data.get("name", None),
        class_name=data.get("className", None),
        idClassList=data.get("idClassList", []),
        handling_option=data.get("handlingOption", "filled"),
        handling_type_list=data.get("handlingTypeList", []),
        has_class=data.get("hasClass", None),
        has_admin_text=data.get("hasAdminText", None),
        has_max_dose_adult=data.get("hasMaxDoseAdult", None),
        has_max_dose_adult_weight=data.get("hasMaxDoseAdultWeight", None),
        has_max_dose_pediatric=data.get("hasMaxDosePediatric", None),
        has_max_dose_pediatric_weight=data.get("hasMaxDosePediatricWeight", None),
        tags=data.get("tags", []),
    )

    return list


@app_admin_subs.route("/admin/substance", methods=["POST"])
@api_endpoint()
def update_substance():
    subs = admin_substance_service.upsert_substance(
        request_data=AdminSubstanceRequest(**request.get_json()),
    )

    return subs
