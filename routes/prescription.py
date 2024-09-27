from flask import Blueprint, request
from markupsafe import escape as escape_html
from datetime import date

from services import (
    prescription_service,
    prescription_drug_service,
    prioritization_service,
    prescription_view_service,
    prescription_check_service,
)
from decorators.api_endpoint_decorator import api_endpoint

app_pres = Blueprint("app_pres", __name__)


@app_pres.route("/prescriptions", methods=["GET"])
@api_endpoint()
def getPrescriptions():
    idSegment = request.args.get("idSegment", None)
    idSegmentList = request.args.getlist("idSegment[]")
    idDept = request.args.getlist("idDept[]")
    idDrug = request.args.getlist("idDrug[]")
    idPatient = request.args.getlist("idPatient[]")
    intervals = request.args.getlist("intervals[]")
    allDrugs = request.args.get("allDrugs", 0)
    startDate = request.args.get("startDate", str(date.today()))
    endDate = request.args.get("endDate", None)
    pending = request.args.get("pending", 0)
    currentDepartment = request.args.get("currentDepartment", 0)
    agg = request.args.get("agg", 0)
    concilia = request.args.get("concilia", 0)
    insurance = request.args.get("insurance", None)
    indicators = request.args.getlist("indicators[]")
    drugAttributes = request.args.getlist("drugAttributes[]")
    frequencies = request.args.getlist("frequencies[]")
    substances = request.args.getlist("substances[]")
    substanceClasses = request.args.getlist("substanceClasses[]")
    patientStatus = request.args.get("patientStatus", None)
    patientReviewType = request.args.get("patientReviewType", None)
    prescriber = request.args.get("prescriber", None)
    diff = request.args.get("diff", None)
    pending_interventions = request.args.get("pendingInterventions", None)
    global_score_min = request.args.get("globalScoreMin", None)
    global_score_max = request.args.get("globalScoreMax", None)

    return prioritization_service.get_prioritization_list(
        idSegment=idSegment,
        idSegmentList=idSegmentList,
        idDept=idDept,
        idDrug=idDrug,
        startDate=startDate,
        endDate=endDate,
        pending=pending,
        agg=agg,
        currentDepartment=currentDepartment,
        concilia=concilia,
        allDrugs=allDrugs,
        insurance=insurance,
        indicators=indicators,
        frequencies=frequencies,
        patientStatus=patientStatus,
        substances=substances,
        substanceClasses=substanceClasses,
        patientReviewType=patientReviewType,
        drugAttributes=drugAttributes,
        idPatient=idPatient,
        intervals=intervals,
        prescriber=prescriber,
        diff=diff,
        global_score_min=global_score_min,
        global_score_max=global_score_max,
        pending_interventions=pending_interventions,
    )


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


@app_pres.route("/static/prescriptions/status", methods=["POST"])
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
    search_key = request.args.get("term", None)

    return prescription_service.search(search_key)


@app_pres.route("/prescriptions/start-evaluation", methods=["POST"])
@api_endpoint()
def start_evaluation():
    data = request.get_json()

    return prescription_service.start_evaluation(
        id_prescription=data.get("idPrescription", None)
    )
