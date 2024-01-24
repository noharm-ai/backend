from flask import Blueprint, request
from datetime import datetime
from flask_jwt_extended import jwt_required, get_jwt_identity

from models.main import *
from models.prescription import *
from .utils import tryCommit
from services import prescription_agg_service
from services.admin import drug_service

from exception.validation_error import ValidationError

app_stc = Blueprint("app_stc", __name__)


@app_stc.route(
    "/static/<string:schema>/prescription/<int:id_prescription>", methods=["GET"]
)
def computePrescription(schema, id_prescription):
    is_cpoe = request.args.get("cpoe", False)
    is_pmc = request.args.get("pmc", False)
    out_patient = request.args.get("outpatient", None)

    try:
        prescription_agg_service.create_agg_prescription_by_prescription(
            schema, id_prescription, is_cpoe, out_patient, is_pmc=is_pmc
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, str(id_prescription))


@app_stc.route(
    "/static/<string:schema>/aggregate/<int:admission_number>", methods=["GET"]
)
def create_aggregated_prescription_by_date(schema, admission_number):
    is_cpoe = request.args.get("cpoe", False)
    str_date = request.args.get("p_date", None)
    p_date = (
        datetime.strptime(str_date, "%Y-%m-%d").date()
        if str_date
        else datetime.today().date()
    )

    try:
        prescription_agg_service.create_agg_prescription_by_date(
            schema, admission_number, p_date, is_cpoe
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, str(admission_number))


@app_stc.route("/static/drug/update-substances")
@jwt_required()
def update_substances():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    try:
        result = drug_service.static_update_substances(user)
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, result)
