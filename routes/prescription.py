"""Route: prescription related endpoints"""

from datetime import date, datetime

from flask import Blueprint, request
from markupsafe import escape as escape_html

from decorators.api_endpoint_decorator import api_endpoint
from models.requests.prioritization_request import PrioritizationRequest
from services import (
    prescription_check_service,
    prescription_drug_service,
    prescription_service,
    prescription_view_service,
    prioritization_service,
)

app_pres = Blueprint("app_pres", __name__)


@app_pres.route("/prescriptions", methods=["GET"])
@api_endpoint()
def get_prescriptions():
    """Prioritize prescriptions"""

    # Helper function to convert string to bool (for non-None defaults)
    def to_bool(value, default=False):
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        return value not in ("0", "false", "False", "")

    # Helper function to convert string to optional bool
    def to_optional_bool(value):
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        return value not in ("0", "false", "False", "")

    # Helper function to convert string list to int list
    def to_int_list(value_list):
        try:
            return [int(v) for v in value_list if v]
        except (ValueError, TypeError):
            return []

    # Helper function to convert string to optional int
    def to_optional_int(value):
        if value is None:
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None

    # Parse dates
    def parse_date(date_str):
        if date_str is None:
            return None
        if isinstance(date_str, date):
            return date_str
        try:
            return datetime.fromisoformat(date_str).date()
        except (ValueError, AttributeError):
            return None

    prioritization_request = PrioritizationRequest(
        idSegment=to_optional_int(request.args.get("idSegment")),
        idSegmentList=to_int_list(request.args.getlist("idSegment[]")),
        idDept=to_int_list(request.args.getlist("idDept[]")),
        idDrug=to_int_list(request.args.getlist("idDrug[]")),
        idPatient=to_int_list(request.args.getlist("idPatient[]")),
        intervals=request.args.getlist("intervals[]"),
        allDrugs=to_bool(request.args.get("allDrugs"), default=False),
        startDate=parse_date(request.args.get("startDate")) or date.today(),
        endDate=parse_date(request.args.get("endDate")),
        pending=to_bool(request.args.get("pending"), default=False),
        currentDepartment=to_bool(request.args.get("currentDepartment"), default=False),
        agg=to_bool(request.args.get("agg"), default=False),
        concilia=to_bool(request.args.get("concilia"), default=False),
        insurance=request.args.get("insurance", None),
        indicators=request.args.getlist("indicators[]"),
        drugAttributes=request.args.getlist("drugAttributes[]"),
        frequencies=request.args.getlist("frequencies[]"),
        substances=to_int_list(request.args.getlist("substances[]")),
        substanceClasses=request.args.getlist("substanceClasses[]"),
        patientStatus=request.args.get("patientStatus", None),
        patientReviewType=to_optional_int(request.args.get("patientReviewType")),
        prescriber=request.args.get("prescriber", None),
        diff=to_optional_bool(request.args.get("diff")),
        pending_interventions=to_optional_bool(
            request.args.get("pendingInterventions")
        ),
        global_score_min=to_optional_int(request.args.get("globalScoreMin")),
        global_score_max=to_optional_int(request.args.get("globalScoreMax")),
        has_conciliation=to_optional_bool(request.args.get("hasConciliation")),
        alert_level=request.args.get("alertLevel", None),
        tags=request.args.getlist("tags[]") or None,
        has_clinical_notes=to_optional_bool(request.args.get("hasClinicalNotes")),
        protocols=to_int_list(request.args.getlist("protocols[]")) or None,
        age_min=to_optional_int(request.args.get("ageMin")),
        age_max=to_optional_int(request.args.get("ageMax")),
        id_patient_by_name_list=to_int_list(
            request.args.getlist("idPatientByNameList[]")
        )
        or None,
        id_icd_list=request.args.getlist("idIcdList[]") or None,
        id_icd_group_list=request.args.getlist("idIcdGroupList[]") or None,
        city=request.args.get("city", None),
        medical_record=request.args.get("medical_record", None),
        bed=request.args.get("bed", None),
    )

    return prioritization_service.get_prioritization_list(prioritization_request)


@app_pres.route("/prescriptions/<int:idPrescription>", methods=["GET"])
@api_endpoint()
def getPrescriptionAuth(idPrescription):
    return prescription_view_service.route_get_prescription(
        id_prescription=idPrescription
    )


@app_pres.route("/prescriptions/<int:idPrescription>", methods=["PUT"])
@api_endpoint()
def setPrescriptionData(idPrescription):
    data = request.get_json()

    prescription_service.update_prescription_data(
        id_prescription=idPrescription, data=data
    )

    return escape_html(str(idPrescription))


@app_pres.route("/prescriptions/status", methods=["POST"])
@api_endpoint()
def setPrescriptionStatus():
    data = request.get_json()

    id_prescription = data.get("idPrescription", None)
    p_status = (
        escape_html(data.get("status", None))
        if data.get("status", None) != None
        else None
    )
    evaluation_time = data.get("evaluationTime", None)
    alerts = data.get("alerts", [])
    fast_check = data.get("fastCheck", False)

    return prescription_check_service.check_prescription(
        idPrescription=id_prescription,
        p_status=p_status,
        evaluation_time=evaluation_time,
        alerts=alerts,
        fast_check=fast_check,
    )


@app_pres.route("/prescriptions/review", methods=["POST"])
@api_endpoint()
def review_prescription():
    data = request.get_json()

    id_prescription = data.get("idPrescription", None)
    evaluation_time = data.get("evaluationTime", None)
    review_type = data.get("reviewType", None)

    return prescription_check_service.review_prescription(
        idPrescription=id_prescription,
        evaluation_time=evaluation_time,
        review_type=review_type,
    )


@app_pres.route("/prescriptions/drug/<int:idPrescriptionDrug>/period", methods=["GET"])
@api_endpoint()
def getDrugPeriod(idPrescriptionDrug):
    return prescription_drug_service.get_drug_period(
        id_prescription_drug=idPrescriptionDrug, future=request.args.get("future", None)
    )


@app_pres.route("/prescriptions/drug/<int:idPrescriptionDrug>", methods=["PUT"])
@api_endpoint()
def setPrescriptionDrugNote(idPrescriptionDrug):
    data = request.get_json()

    return prescription_drug_service.update_prescription_drug_data(
        id_prescription_drug=idPrescriptionDrug, data=data
    )


@app_pres.route("/prescriptions/drug/form", methods=["PUT"])
@api_endpoint()
def update_form():
    data = request.get_json()

    prescription_drug_service.update_pd_form(data)

    return True


@app_pres.route("/prescriptions/<int:idPrescription>/update", methods=["GET"])
@api_endpoint()
def getPrescriptionUpdate(idPrescription):
    prescription_service.recalculate_prescription(id_prescription=idPrescription)
    return escape_html(str(idPrescription))


@app_pres.route("/prescriptions/search", methods=["GET"])
@api_endpoint()
def search_prescriptions():
    """fast search prescriptions"""
    search_key = request.args.get("term", None)

    return prescription_service.search(search_key)


@app_pres.route("/prescriptions/start-evaluation", methods=["POST"])
@api_endpoint()
def start_evaluation():
    """save user currently evaluating prescription"""
    data = request.get_json()

    return prescription_service.start_evaluation(
        id_prescription=data.get("idPrescription", None)
    )


@app_pres.route("/prescriptions/pep-link", methods=["GET"])
@api_endpoint()
def pep_link():
    """get custom link for user to access their local pep"""
    return prescription_service.get_pep_link(
        id_prescription=request.args.get("idPrescription", None)
    )
