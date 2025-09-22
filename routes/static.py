"""Route: prescalc and atend calc endpoints"""

import logging
from datetime import datetime

from flask import Blueprint, request, g
from markupsafe import escape as escape_html

from models.main import db, User
from services import (
    prescription_agg_service,
    prescription_check_service,
)
from exception.validation_error import ValidationError
from exception.authorization_error import AuthorizationError
from utils import status, sessionutils
from decorators.api_endpoint_decorator import api_endpoint

app_stc = Blueprint("app_stc", __name__)


@app_stc.route(
    "/static/<string:schema>/prescription/<int:id_prescription>", methods=["GET"]
)
def create_aggregated_by_prescription(schema, id_prescription):
    out_patient = request.args.get("outpatient", None)
    force = request.args.get("force", False)

    user_context = User()
    user_context.id = 0
    user_context.schema = schema
    user_context.config = {"roles": ["STATIC_USER"]}
    g.user_context = user_context

    try:
        prescription_agg_service.create_agg_prescription_by_prescription(
            schema=schema,
            id_prescription=id_prescription,
            out_patient=out_patient,
            force=force,
            user_context=user_context,
        )
    except ValidationError as e:
        db.session.rollback()

        logging.basicConfig()
        logger = logging.getLogger("noharm.backend")
        logger.warning(
            "(%s) VALIDATION4xx: %s",
            user_context.schema if user_context else "undefined",
            str(e),
        )
        logger.warning(
            "schema: %s", user_context.schema if user_context else "undefined"
        )

        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus
    except AuthorizationError:
        db.session.rollback()

        logging.basicConfig()
        logger = logging.getLogger("noharm.backend")
        logger.warning(
            "(%s) VALIDATION4xx: static usuário inválido",
            user_context.schema if user_context else "undefined",
        )
        logger.warning(
            "schema: %s", user_context.schema if user_context else "undefined"
        )

        return {
            "status": "error",
            "message": "Usuário inválido",
            "code": "errors.unauthorized",
        }, status.HTTP_401_UNAUTHORIZED

    return sessionutils.tryCommit(db, escape_html(str(id_prescription)))


@app_stc.route(
    "/static/<string:schema>/aggregate/<int:admission_number>", methods=["GET"]
)
def create_aggregated_prescription_by_date(schema, admission_number):
    str_date = request.args.get("p_date", None)
    p_date = (
        datetime.strptime(str_date, "%Y-%m-%d").date()
        if str_date
        else datetime.today().date()
    )

    user_context = User()
    user_context.id = 0
    user_context.schema = schema
    user_context.config = {"roles": ["STATIC_USER"]}
    g.user_context = user_context

    try:
        prescription_agg_service.create_agg_prescription_by_date(
            schema, admission_number, p_date, user_context=user_context
        )
    except ValidationError as e:
        db.session.rollback()

        logging.basicConfig()
        logger = logging.getLogger("noharm.backend")
        logger.warning(
            "(%s) VALIDATION4xx: %s",
            user_context.schema if user_context else "undefined",
            str(e),
        )
        logger.warning(
            "schema: %s", user_context.schema if user_context else "undefined"
        )

        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus
    except AuthorizationError:
        db.session.rollback()

        logging.basicConfig()
        logger = logging.getLogger("noharm.backend")
        logger.warning(
            "(%s) VALIDATION4xx: static usuário inválido",
            user_context.schema if user_context else "undefined",
        )
        logger.warning(
            "schema: %s", user_context.schema if user_context else "undefined"
        )

        return {
            "status": "error",
            "message": "Usuário inválido",
            "code": "errors.unauthorized",
        }, status.HTTP_401_UNAUTHORIZED

    return sessionutils.tryCommit(db, escape_html(str(admission_number)))


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
