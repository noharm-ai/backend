"""Route: prescription related endpoints"""

from datetime import date, datetime

from flask import Blueprint, request
from werkzeug.datastructures import MultiDict
from markupsafe import escape as escape_html

from decorators.api_endpoint_decorator import api_endpoint
from models.requests.allergy_request import AllergySubstanceRequest
from models.requests.interaction_trace_request import InteractionTraceRequest
from models.requests.prioritization_request import PrioritizationRequest
from services import (
    allergy_service,
    interaction_trace_service,
    prescription_check_service,
    prescription_drug_service,
    prescription_service,
    prescription_view_service,
    prioritization_service,
)

app_pres = Blueprint("app_pres", __name__)


@app_pres.route("/prescriptions", methods=["GET", "POST"])
@api_endpoint()
def get_prescriptions():
    """Prioritize prescriptions.

    The filters come as query string (GET) or as a JSON body (POST). The
    frontend posts them: a long list of filters makes the URL too long for the
    server (414 Request-URI Too Large).
    """
    args = (
        _json_body_to_args(request.get_json(silent=True) or {})
        if request.method == "POST"
        else request.args
    )

    return prioritization_service.get_prioritization_list(
        _build_prioritization_request(args)
    )


def _json_body_to_args(body: dict) -> MultiDict:
    """Turn the JSON body into the query string shape the GET reads.

    A list goes under ``key[]`` (as axios writes it in the query string) and a
    scalar under ``key``; ``null`` is left out, so both methods filter alike.
    """
    args = MultiDict()

    if not isinstance(body, dict):
        return args

    for key, value in body.items():
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            for item in value:
                if item is not None:
                    args.add(f"{key}[]", _to_arg(item))
        else:
            args.add(key, _to_arg(value))

    return args


def _to_arg(value) -> str:
    """Write a JSON value as axios writes it in the query string."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _build_prioritization_request(args: MultiDict) -> PrioritizationRequest:
    """Build the prioritization request from the query string args."""

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

    return PrioritizationRequest(
        idSegment=to_optional_int(args.get("idSegment")),
        idSegmentList=to_int_list(args.getlist("idSegment[]")),
        idDept=to_int_list(args.getlist("idDept[]")),
        idDrug=to_int_list(args.getlist("idDrug[]")),
        idPatient=to_int_list(args.getlist("idPatient[]")),
        intervals=args.getlist("intervals[]"),
        first_administration_hour=args.getlist("first_administration_hour[]"),
        allDrugs=to_bool(args.get("allDrugs"), default=False),
        startDate=parse_date(args.get("startDate")) or date.today(),
        endDate=parse_date(args.get("endDate")),
        pending=to_bool(args.get("pending"), default=False),
        currentDepartment=to_bool(args.get("currentDepartment"), default=False),
        agg=to_bool(args.get("agg"), default=False),
        concilia=to_bool(args.get("concilia"), default=False),
        insurance=args.get("insurance", None),
        indicators=args.getlist("indicators[]"),
        drugAttributes=args.getlist("drugAttributes[]"),
        frequencies=args.getlist("frequencies[]"),
        substances=to_int_list(args.getlist("substances[]")),
        substanceClasses=args.getlist("substanceClasses[]"),
        patientStatus=args.get("patientStatus", None),
        patientReviewType=to_optional_int(args.get("patientReviewType")),
        prescriber=args.get("prescriber", None),
        diff=to_optional_bool(args.get("diff")),
        pending_interventions=to_optional_bool(
            args.get("pendingInterventions")
        ),
        global_score_min=to_optional_int(args.get("globalScoreMin")),
        global_score_max=to_optional_int(args.get("globalScoreMax")),
        has_conciliation=to_optional_bool(args.get("hasConciliation")),
        alert_level=args.get("alertLevel", None),
        tags=args.getlist("tags[]") or None,
        has_clinical_notes=to_optional_bool(args.get("hasClinicalNotes")),
        protocols=to_int_list(args.getlist("protocols[]")) or None,
        age_min=to_optional_int(args.get("ageMin")),
        age_max=to_optional_int(args.get("ageMax")),
        id_patient_by_name_list=to_int_list(
            args.getlist("idPatientByNameList[]")
        )
        or None,
        id_icd_list=args.getlist("idIcdList[]") or None,
        id_icd_group_list=args.getlist("idIcdGroupList[]") or None,
        city=args.get("city", None),
        medical_record=args.get("medical_record", None),
        medical_record_list=to_int_list(args.getlist("medicalRecordList[]"))
        or None,
        bed=args.get("bed", None),
        bed_list=args.getlist("bedList[]") or None,
        specialty_list=args.getlist("specialtyList[]") or None,
        responsible_physician_list=args.getlist("responsiblePhysicianList[]")
        or None,
    )


@app_pres.route("/prescriptions/interaction-trace", methods=["GET"])
@api_endpoint()
def trace_interaction():
    """Explain why an interaction alert was or was not raised between two items"""
    return interaction_trace_service.trace_interaction(
        request_data=InteractionTraceRequest(**request.args.to_dict(flat=True))
    )


@app_pres.route("/prescriptions/<int:id_prescription>/allergy-records", methods=["GET"])
@api_endpoint()
def list_allergy_records(id_prescription: int):
    """Every allergy record of the prescription's patient, for maintainers"""
    return allergy_service.list_allergy_records(id_prescription=id_prescription)


@app_pres.route("/allergy-records/substance", methods=["PUT"])
@api_endpoint()
def update_allergy_substance():
    """Set the substance of the allergy records of a drug name, for maintainers"""
    return allergy_service.update_allergy_substance(
        request_data=AllergySubstanceRequest(**request.get_json())
    )


@app_pres.route("/prescriptions/<int:idPrescription>", methods=["GET"])
@api_endpoint()
def getPrescriptionAuth(idPrescription):
    return prescription_view_service.route_get_prescription(
        id_prescription=idPrescription
    )


@app_pres.route("/prescriptions/<int:idPrescription>/cultures", methods=["GET"])
@api_endpoint()
def get_prescription_cultures(idPrescription):
    return prescription_view_service.route_get_prescription_cultures(
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
    concilia_list = data.get("conciliaList", None)
    concilia_relations = data.get("conciliaRelations", None)

    return prescription_check_service.check_prescription(
        idPrescription=id_prescription,
        p_status=p_status,
        evaluation_time=evaluation_time,
        alerts=alerts,
        fast_check=fast_check,
        concilia_list=concilia_list,
        concilia_relations=concilia_relations,
    )


@app_pres.route("/prescriptions/status-list", methods=["POST"])
@api_endpoint()
def getPrescriptionsStatusList():
    """Return status for a list of idPrescription (lightweight refresh, no filters/joins)"""
    data = request.get_json()
    id_prescription_list = data.get("idPrescriptionList", [])

    try:
        id_prescription_list = [int(i) for i in id_prescription_list if i]
    except (ValueError, TypeError):
        id_prescription_list = []

    return prescription_service.get_prescriptions_status(id_prescription_list)


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


@app_pres.route(
    "/prescriptions/drug/<int:id_prescription_drug>/check-history", methods=["GET"]
)
@api_endpoint()
def get_drug_check_history(id_prescription_drug: int):
    """List check history for a prescription drug from checkedindex table"""
    return prescription_drug_service.get_drug_check_history(
        id_prescription_drug=id_prescription_drug
    )
