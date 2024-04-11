from flask_api import status
from models.main import *
from models.appendix import *
from models.prescription import *
from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime
from .utils import tryCommit
from services.admin import intervention_reason_service
from services import intervention_service, memory_service
from exception.validation_error import ValidationError

app_itrv = Blueprint("app_itrv", __name__)


@app_itrv.route(
    "/prescriptions/drug/<int:idPrescriptionDrug>/<int:drugStatus>", methods=["PUT"]
)
@jwt_required()
def setDrugStatus(idPrescriptionDrug, drugStatus):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    pd = PrescriptionDrug.query.get(idPrescriptionDrug)
    if pd is not None:
        pd.status = drugStatus
        pd.update = datetime.today()
        pd.user = user.id

    return tryCommit(db, str(idPrescriptionDrug), user.permission())


@app_itrv.route("/intervention", methods=["PUT"])
@jwt_required()
def save_intervention():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    data = request.get_json()

    try:
        intervention = intervention_service.save_intervention(
            id_intervention=data.get("idIntervention", None),
            id_prescription=data.get("idPrescription", "0"),
            id_prescription_drug=data.get("idPrescriptionDrug", "0"),
            new_status=data.get("status", "s"),
            user=user,
            admission_number=data.get("admissionNumber", None),
            id_intervention_reason=data.get("idInterventionReason", None),
            error=data.get("error", None),
            cost=data.get("cost", None),
            observation=data.get("observation", None),
            interactions=data.get("interactions", None),
            transcription=data.get("transcription", None),
            economy_days=data.get("economyDays", None) if "economyDays" in data else -1,
            expended_dose=(
                data.get("expendedDose", None) if "expendedDose" in data else -1
            ),
            agg_id_prescription=data.get("aggIdPrescription", None),
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, intervention, user.permission())


def sortReasons(e):
    return e["description"]


@app_itrv.route("/intervention/reasons", methods=["GET"])
@jwt_required()
def getInterventionReasons():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    list = intervention_reason_service.get_reasons(active_only=True)

    return {
        "status": "success",
        "data": intervention_reason_service.list_to_dto(list),
    }, status.HTTP_200_OK


@app_itrv.route("/intervention/search", methods=["POST"])
@jwt_required()
def search_interventions():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    data = request.get_json()

    results = intervention_service.get_interventions(
        admissionNumber=data.get("admissionNumber", None),
        startDate=data.get("startDate", None),
        endDate=data.get("endDate", None),
        idSegment=data.get("idSegment", None),
        idPrescription=data.get("idPrescription", None),
        idPrescriptionDrug=data.get("idPrescriptionDrug", None),
        idDrug=data.get("idDrug", None),
    )

    return {"status": "success", "data": results}, status.HTTP_200_OK


@app_itrv.route("/intervention/outcome-data", methods=["GET"])
@jwt_required()
def outcome_data():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    try:
        intervention = intervention_service.get_outcome_data(
            id_intervention=request.args.get("idIntervention", None),
            user=user,
            edit=request.args.get("edit", False),
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return {"status": "success", "data": intervention}, status.HTTP_200_OK


@app_itrv.route("/intervention/set-outcome", methods=["POST"])
@jwt_required()
def set_outcome():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    data = request.get_json()

    try:
        intervention_service.set_intervention_outcome(
            id_intervention=data.get("idIntervention", None),
            outcome=data.get("outcome", None),
            user=user,
            economy_day_amount=data.get("economyDayAmount", None),
            economy_day_amount_manual=data.get("economyDayAmountManual", None),
            economy_day_value=data.get("economyDayValue", None),
            economy_day_value_manual=data.get("economyDayValueManual", None),
            id_prescription_drug_destiny=data.get("idPrescriptionDrugDestiny", None),
            origin_data=data.get("origin"),
            destiny_data=data.get("destiny"),
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, True, user.permission())
