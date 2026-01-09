"""Route: prescalc and atend calc endpoints"""

import json

from flask import Blueprint, request
from markupsafe import escape as escape_html

from decorators.api_endpoint_decorator import api_endpoint
from services import (
    prescription_check_service,
)
from utils import logger, status

app_stc = Blueprint("app_stc", __name__)


@app_stc.route(
    "/static/<string:schema>/prescription/<int:id_prescription>", methods=["GET"]
)
def create_aggregated_by_prescription(schema, id_prescription):
    """DEPRECATED: use prescalc central instead"""

    logger.backend_logger.warning(
        json.dumps(
            {
                "event": "validation_error",
                "path": request.path,
                "schema": schema,
                "message": "prescalc central ligado, abortando",
            }
        )
    )

    return {"status": "success", "data": int(id_prescription)}, status.HTTP_200_OK


@app_stc.route(
    "/static/<string:schema>/aggregate/<int:admission_number>", methods=["GET"]
)
def create_aggregated_prescription_by_date(schema, admission_number):
    """DEPRECATED: use prescalc central instead"""

    logger.backend_logger.warning(
        json.dumps(
            {
                "event": "validation_error",
                "path": request.path,
                "schema": schema,
                "message": "prescalc central ligado, abortando",
            }
        )
    )
    return {"status": "success", "data": int(admission_number)}, status.HTTP_200_OK


@app_stc.route("/static/prescriptions/status", methods=["POST"])
@api_endpoint()
def static_prescription_status():
    data = request.get_json()

    id_prescription = data.get("idPrescription", None)
    p_status = (
        escape_html(data.get("status", None))
        if data.get("status", None) != None
        else None
    )
    id_origin_user = data.get("idOriginUser", None)

    return prescription_check_service.static_check(
        id_prescription=id_prescription,
        p_status=p_status,
        id_origin_user=id_origin_user,
    )
