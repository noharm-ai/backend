from flask import Blueprint, request

from services.admin import admin_intervention_reason_service
from services import intervention_service
from decorators.api_endpoint_decorator import api_endpoint

app_itrv = Blueprint("app_itrv", __name__)


@app_itrv.route("/intervention", methods=["PUT"])
@api_endpoint()
def save_intervention():
    data = request.get_json()

    id_prescription_drug_list = data.get("idPrescriptionDrugList", [])

    if len(id_prescription_drug_list) > 0:
        result = intervention_service.add_multiple_interventions(
            id_prescription_drug_list=id_prescription_drug_list,
            admission_number=data.get("admissionNumber", None),
            id_intervention_reason=data.get("idInterventionReason", None),
            error=data.get("error", None),
            cost=data.get("cost", None),
            observation=data.get("observation", None),
            agg_id_prescription=data.get("aggIdPrescription", None),
        )
    else:
        result = intervention_service.save_intervention(
            id_intervention=data.get("idIntervention", None),
            id_prescription=data.get("idPrescription", "0"),
            id_prescription_drug=data.get("idPrescriptionDrug", "0"),
            new_status=data.get("status", "s"),
            admission_number=data.get("admissionNumber", None),
            id_intervention_reason=data.get("idInterventionReason", None),
            error=data.get("error", None),
            cost=data.get("cost", None),
            observation=data.get("observation", None),
            interactions=data.get("interactions", None),
            transcription=data.get("transcription", None),
            economy_days=(
                data.get("economyDays", None) if "economyDays" in data else -1
            ),
            expended_dose=(
                data.get("expendedDose", None) if "expendedDose" in data else -1
            ),
            agg_id_prescription=data.get("aggIdPrescription", None),
            update_responsible=data.get("updateResponsible", False),
        )

    return result


def sortReasons(e):
    return e["description"]


@app_itrv.route("/intervention/reasons", methods=["GET"])
@api_endpoint()
def getInterventionReasons():
    list = admin_intervention_reason_service.get_reasons(active_only=True)

    return admin_intervention_reason_service.list_to_dto(list)


@app_itrv.route("/intervention/search", methods=["POST"])
@api_endpoint()
def search_interventions():
    data = request.get_json()

    return intervention_service.get_interventions(
        admissionNumber=data.get("admissionNumber", None),
        startDate=data.get("startDate", None),
        endDate=data.get("endDate", None),
        idSegment=data.get("idSegment", None),
        idPrescription=data.get("idPrescription", None),
        idPrescriptionDrug=data.get("idPrescriptionDrug", None),
        idDrug=data.get("idDrug", None),
        id_intervention_reason_list=data.get("idInterventionReasonList", []),
        has_economy=data.get("hasEconomy", None),
        status_list=data.get("statusList", []),
        responsible_name=data.get("responsibleName", None),
        prescriber_name=data.get("prescriberName", None),
    )


@app_itrv.route("/intervention/outcome-data", methods=["GET"])
@api_endpoint()
def outcome_data():
    return intervention_service.get_outcome_data(
        id_intervention=request.args.get("idIntervention", None),
        edit=request.args.get("edit", False),
    )


@app_itrv.route("/intervention/set-outcome", methods=["POST"])
@api_endpoint()
def set_outcome():
    data = request.get_json()

    intervention_service.set_intervention_outcome(
        id_intervention=data.get("idIntervention", None),
        outcome=data.get("outcome", None),
        economy_day_amount=data.get("economyDayAmount", None),
        economy_day_amount_manual=data.get("economyDayAmountManual", None),
        economy_day_value=data.get("economyDayValue", None),
        economy_day_value_manual=data.get("economyDayValueManual", None),
        id_prescription_drug_destiny=data.get("idPrescriptionDrugDestiny", None),
        origin_data=data.get("origin"),
        destiny_data=data.get("destiny"),
    )

    return True
