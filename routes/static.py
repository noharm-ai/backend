from flask import Blueprint, request, g
from markupsafe import escape as escape_html
from datetime import datetime

from models.main import db, User
from .utils import tryCommit
from services import prescription_agg_service

from exception.validation_error import ValidationError
from exception.authorization_error import AuthorizationError
from utils import status

app_stc = Blueprint("app_stc", __name__)


@app_stc.route(
    "/static/<string:schema>/prescription/<int:id_prescription>", methods=["GET"]
)
def computePrescription(schema, id_prescription):
    is_cpoe = request.args.get("cpoe", False)
    is_pmc = request.args.get("pmc", False)
    out_patient = request.args.get("outpatient", None)
    force = request.args.get("force", False)

    user_context = User()
    user_context.config = {"roles": ["STATIC_USER"]}
    g.user_context = user_context

    try:
        prescription_agg_service.create_agg_prescription_by_prescription(
            schema, id_prescription, is_cpoe, out_patient, is_pmc=is_pmc, force=force
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus
    except AuthorizationError as e:
        return {
            "status": "error",
            "message": "Usuário inválido",
            "code": "errors.unauthorized",
        }, status.HTTP_401_UNAUTHORIZED

    return tryCommit(db, escape_html(str(id_prescription)))


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

    user_context = User()
    user_context.config = {"roles": ["STATIC_USER"]}
    g.user_context = user_context

    try:
        prescription_agg_service.create_agg_prescription_by_date(
            schema, admission_number, p_date, is_cpoe
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus
    except AuthorizationError as e:
        return {
            "status": "error",
            "message": "Usuário inválido",
            "code": "errors.unauthorized",
        }, status.HTTP_401_UNAUTHORIZED

    return tryCommit(db, escape_html(str(admission_number)))
