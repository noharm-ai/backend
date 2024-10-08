import os
import random
import logging
from utils import status
from models.main import *
from models.appendix import *
from models.segment import *
from models.prescription import *
from models.notes import ClinicalNotes
from flask import Blueprint, request
from markupsafe import escape as escape_html
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    jwt_required,
    get_jwt_identity,
    verify_jwt_in_request,
)
from .utils import *
from sqlalchemy import func, between, text
from datetime import date, datetime
from .drugList import DrugList
from services import (
    alert_service,
    alert_interaction_service,
    memory_service,
    prescription_service,
    prescription_drug_service,
    intervention_service,
    patient_service,
    data_authorization_service,
    permission_service,
    clinical_notes_service,
)
from models.enums import (
    MemoryEnum,
    FeatureEnum,
    PrescriptionAuditTypeEnum,
    PrescriptionReviewTypeEnum,
)
from exception.validation_error import ValidationError

app_pres = Blueprint("app_pres", __name__)


@app_pres.route("/prescriptions", methods=["GET"])
@jwt_required()
def getPrescriptions():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

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

    patients = Patient.getPatients(
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
        is_cpoe=user.cpoe(),
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

    results = []
    for p in patients:
        patient = p[1]
        if patient is None:
            patient = Patient()
            patient.idPatient = p[0].idPatient
            patient.admissionNumber = p[0].admissionNumber

        featuresNames = [
            "alerts",
            "prescriptionScore",
            "scoreOne",
            "scoreTwo",
            "scoreThree",
            "am",
            "av",
            "controlled",
            "np",
            "tube",
            "diff",
            "alertExams",
            "interventions",
            "complication",
            "alertLevel",
        ]

        features = {"processed": True}
        if p[0].features:
            for f in featuresNames:
                features[f] = p[0].features[f] if f in p[0].features else 0

            features["globalScore"] = none2zero(p.globalScore)

            if features["globalScore"] > 90:
                features["class"] = "red"
            elif features["globalScore"] > 60:
                features["class"] = "orange"
            elif features["globalScore"] > 10:
                features["class"] = "yellow"
            else:
                features["class"] = "green"

            features["alertStats"] = (
                p[0].features["alertStats"] if "alertStats" in p[0].features else None
            )
        else:
            features["processed"] = False
            features["globalScore"] = 0
            features["class"] = "blue"

        observation = None
        if p[1] and p[1].observation != None and p[1].observation != "":
            observation = (
                p[1].observation[:300] + "..."
                if len(p[1].observation) > 300
                else p[1].observation
            )

        results.append(
            dict(
                features,
                **{
                    "idPrescription": str(p[0].id),
                    "idPatient": str(p[0].idPatient),
                    "name": patient.admissionNumber,
                    "admissionNumber": patient.admissionNumber,
                    "idSegment": p[0].idSegment,
                    "birthdate": (
                        patient.birthdate.isoformat() if patient.birthdate else None
                    ),
                    "gender": patient.gender,
                    "weight": patient.weight,
                    "skinColor": patient.skinColor,
                    "lengthStay": lenghStay(patient.admissionDate),
                    "dischargeDate": (
                        patient.dischargeDate.isoformat()
                        if patient.dischargeDate
                        else None
                    ),
                    "dischargeReason": patient.dischargeReason,
                    "date": p[0].date.isoformat(),
                    "department": str(p[2]),
                    "insurance": p[0].insurance,
                    "bed": p[0].bed,
                    "status": p[0].status,
                    "isBeingEvaluated": prescription_service.is_being_evaluated(
                        p[0].features
                    ),
                    "reviewType": p[0].reviewType,
                    "observation": observation,
                    "totalRecords": p[3],
                    "agg": p[0].agg,
                    "prescriptionAggId": gen_agg_id(
                        admission_number=p[0].admissionNumber,
                        id_segment=p[0].idSegment,
                        pdate=p[0].date,
                    ),
                },
            )
        )

    return {"status": "success", "data": results}, status.HTTP_200_OK


@app_pres.route("/prescriptions/<int:idPrescription>", methods=["GET"])
@jwt_required()
def getPrescriptionAuth(idPrescription):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    p = Prescription.getPrescription(idPrescription)

    if p is None:
        return {
            "status": "error",
            "message": "Prescrição Inexistente!",
        }, status.HTTP_400_BAD_REQUEST

    if p[0].agg:
        return getPrescription(
            idPrescription=idPrescription,
            admissionNumber=p[0].admissionNumber,
            aggDate=p[0].date,
            idSegment=p[0].idSegment,
            is_cpoe=user.cpoe(),
            is_pmc=memory_service.has_feature("PRIMARYCARE"),
            is_complete=True,
        )
    else:
        return getPrescription(idPrescription=idPrescription, is_complete=True)


def buildHeaders(headers, pDrugs, pSolution, pProcedures):
    for pid in headers.keys():
        drugs = [d for d in pDrugs if int(d["idPrescription"]) == pid]
        drugsInterv = [
            d["prevIntervention"] for d in drugs if d["prevIntervention"] != {}
        ]

        solutions = [s for s in pSolution if int(s["idPrescription"]) == pid]
        solutionsInterv = [
            s["prevIntervention"] for s in solutions if s["prevIntervention"] != {}
        ]

        procedures = [p for p in pProcedures if int(p["idPrescription"]) == pid]
        proceduresInterv = [
            p["prevIntervention"] for p in procedures if p["prevIntervention"] != {}
        ]

        headers[pid]["drugs"] = getFeatures(
            {
                "data": {
                    "prescription": drugs,
                    "solution": [],
                    "procedures": [],
                    "interventions": drugsInterv,
                    "alertExams": [],
                    "complication": 0,
                }
            }
        )
        headers[pid]["solutions"] = getFeatures(
            {
                "data": {
                    "prescription": [],
                    "solution": solutions,
                    "procedures": [],
                    "interventions": solutionsInterv,
                    "alertExams": [],
                    "complication": 0,
                }
            }
        )
        headers[pid]["procedures"] = getFeatures(
            {
                "data": {
                    "prescription": [],
                    "solution": [],
                    "procedures": procedures,
                    "interventions": proceduresInterv,
                    "alertExams": [],
                    "complication": 0,
                }
            }
        )

    return headers


def getPrevIntervention(interventions, dtPrescription):
    result = False
    for i in interventions:
        if (
            int(i["id"]) == 0
            and i["status"] == "s"
            and datetime.fromisoformat(i["date"])
            < datetime(
                dtPrescription.year, dtPrescription.month, dtPrescription.day, 0, 0
            )
        ):
            result = True
    return result


def getExistIntervention(interventions, dtPrescription):
    result = False
    for i in interventions:
        if int(i["id"]) == 0 and datetime.fromisoformat(i["date"]) < datetime(
            dtPrescription.year, dtPrescription.month, dtPrescription.day, 0, 0
        ):
            result = True
    return result


def _log_perf(start_date, section):
    end_date = datetime.now()
    logging.basicConfig()
    logger = logging.getLogger("noharm.backend")

    logger.debug(f"PERF {section}: {(end_date-start_date).total_seconds()}")


def getPrescription(
    idPrescription=None,
    admissionNumber=None,
    aggDate=None,
    idSegment=None,
    is_cpoe=False,
    is_pmc=False,
    is_complete=False,
):
    start_date = datetime.now()

    if idPrescription:
        prescription = Prescription.getPrescription(idPrescription)
    else:
        prescription = Prescription.getPrescriptionAgg(
            admissionNumber, aggDate, idSegment
        )

    if prescription is None:
        return {
            "status": "error",
            "message": "Prescrição Inexistente!",
        }, status.HTTP_400_BAD_REQUEST

    patient = prescription[1]
    patientWeight = None
    patientWeightDate = None
    patientHeight = None

    if patient is None:
        patient = Patient()
        patient.idPatient = prescription[0].idPatient
        patient.admissionNumber = prescription[0].admissionNumber

    if patient.weight != None:
        patientWeight = patient.weight
        patientWeightDate = patient.weightDate
        patientHeight = patient.height
    else:
        patient_previous_data = patient_service.get_patient_weight(patient.idPatient)

        if patient_previous_data != None:
            patientWeight = patient_previous_data[0]
            patientWeightDate = patient_previous_data[1]
            patientHeight = patient_previous_data[2]

    lastDept = Prescription.lastDeptbyAdmission(
        prescription[0].id,
        patient.admissionNumber,
        ref_date=aggDate if aggDate != None else prescription[0].date,
    )

    _log_perf(start_date, "GET PRESCRIPTION")

    start_date = datetime.now()
    drugs = PrescriptionDrug.findByPrescription(
        prescription[0].id, patient.admissionNumber, aggDate, idSegment, is_cpoe, is_pmc
    )
    interventions = intervention_service.get_interventions(
        admissionNumber=patient.admissionNumber
    )
    headers = (
        Prescription.getHeaders(admissionNumber, aggDate, idSegment, is_pmc, is_cpoe)
        if aggDate
        else []
    )
    _log_perf(start_date, "GET DRUGS AND INTERVENTIONS")

    # get memory configurations
    start_date = datetime.now()
    memory_itens = memory_service.get_by_kind(
        [
            MemoryEnum.PRESMED_FORM.value,
            MemoryEnum.ADMISSION_REPORTS.value,
            MemoryEnum.ADMISSION_REPORTS_INTERNAL.value,
            MemoryEnum.MAP_SCHEDULES_FASTING.value,
        ]
    )

    formTemplate = memory_itens.get(MemoryEnum.PRESMED_FORM.value, None)
    admission_reports = memory_itens.get(MemoryEnum.ADMISSION_REPORTS.value, None)
    admission_reports_internal = memory_itens.get(
        MemoryEnum.ADMISSION_REPORTS_INTERNAL.value, []
    )
    schedules_fasting = memory_itens.get(MemoryEnum.MAP_SCHEDULES_FASTING.value, [])
    _log_perf(start_date, "GET MEMORY CONFIG")

    start_date = datetime.now()

    p_cache: Prescription = (
        db.session.query(Prescription)
        .filter(
            Prescription.id
            == gen_agg_id(
                admission_number=prescription[0].admissionNumber,
                id_segment=prescription[0].idSegment,
                pdate=datetime.today(),
            )
        )
        .first()
    )

    if (
        p_cache != None
        and p_cache.features != None
        and p_cache.features.get("clinicalNotesStats", None) != None
    ):
        cn_stats = p_cache.features.get("clinicalNotesStats")
    else:
        cn_stats = clinical_notes_service.get_admission_stats(
            admission_number=prescription[0].admissionNumber,
        )

    if (
        p_cache != None
        and p_cache.features != None
        and p_cache.features.get("clinicalNotes", 0) != 0
    ):
        cn_count = p_cache.features.get("clinicalNotes", 0)
    else:
        cn_count = clinical_notes_service.get_count(
            admission_number=prescription[0].admissionNumber,
            admission_date=patient.admissionDate,
        )

    notesSigns = None
    notesInfo = None
    notesAllergies = []
    notesDialysis = None

    if cn_count > 0 and is_complete:
        # TODO: add cache
        if cn_stats.get("signs", 0) != 0:
            notesSigns = ClinicalNotes.getSigns(prescription[0].admissionNumber)

        notesInfo = ClinicalNotes.getInfo(prescription[0].admissionNumber)

        allergies = ClinicalNotes.getAllergies(
            prescription[0].admissionNumber, admission_date=patient.admissionDate
        )
        dialysis = ClinicalNotes.getDialysis(prescription[0].admissionNumber)

        for a in allergies:
            notesAllergies.append(
                {
                    "date": a[1].isoformat(),
                    "text": a[0],
                    "source": "care",
                    "id": str(a[2]),
                }
            )

        notesDialysis = []
        for a in dialysis:
            notesDialysis.append(
                {"date": a[1].isoformat(), "text": a[0], "id": str(a[3])}
            )

    _log_perf(start_date, "GET CLINICAL NOTES")

    start_date = datetime.now()
    registeredAllergies = patient_service.get_patient_allergies(patient.idPatient)
    for a in registeredAllergies:
        notesAllergies.append({"date": a[0], "text": a[1], "source": "pep"})

    exams = Exams.findLatestByAdmission(
        patient, prescription[0].idSegment, prevEx=is_complete
    )
    age = data2age(
        patient.birthdate.isoformat() if patient.birthdate else date.today().isoformat()
    )

    examsJson = []
    alertExams = 0
    for e in exams:
        examsJson.append({"key": e, "value": exams[e]})
        alertExams += int(exams[e]["alert"])

    exams = dict(
        exams, **{"age": age, "weight": patientWeight, "height": patientHeight}
    )
    _log_perf(start_date, "ALLERGIES AND EXAMS")

    start_date = datetime.now()
    relations = alert_interaction_service.find_relations(
        drug_list=drugs, is_cpoe=is_cpoe, id_patient=patient.idPatient
    )
    alerts = alert_service.find_alerts(
        drug_list=drugs,
        exams=exams,
        dialisys=patient.dialysis,
        pregnant=patient.pregnant,
        lactating=patient.lactating,
        schedules_fasting=schedules_fasting,
    )

    drugList = DrugList(
        drugs,
        interventions,
        relations,
        exams,
        aggDate is not None,
        patient.dialysis,
        alerts,
        is_cpoe,
    )
    _log_perf(start_date, "ALERTS")

    start_date = datetime.now()
    disable_solution_tab = memory_service.has_feature(
        FeatureEnum.DISABLE_SOLUTION_TAB.value
    )

    if disable_solution_tab:
        pDrugs = drugList.getDrugType([], ["Medicamentos", "Soluções"])
    else:
        pDrugs = drugList.getDrugType([], ["Medicamentos"])

    reviewed = False
    reviewed_by = None
    reviewed_at = None
    if prescription[0].reviewType == PrescriptionReviewTypeEnum.REVIEWED.value:
        reviewed = True

        if is_complete:
            reviewed_log = (
                db.session.query(PrescriptionAudit, User)
                .join(User, PrescriptionAudit.createdBy == User.id)
                .filter(PrescriptionAudit.idPrescription == prescription[0].id)
                .filter(
                    PrescriptionAudit.auditType
                    == PrescriptionAuditTypeEnum.REVISION.value
                )
                .order_by(desc(PrescriptionAudit.createdAt))
                .first()
            )

            if reviewed_log != None:
                reviewed_by = reviewed_log[1].name
                reviewed_at = reviewed_log[0].createdAt.isoformat()

    conciliaList = []
    if prescription[0].concilia:
        pDrugs = drugList.changeDrugName(pDrugs)
        last_agg_prescription = _get_last_agg_prescription(patient.admissionNumber)
        if last_agg_prescription != None:
            concilia_drugs = PrescriptionDrug.findByPrescription(
                last_agg_prescription.id,
                patient.admissionNumber,
                last_agg_prescription.date,
                idSegment=None,
                is_cpoe=is_cpoe,
            )
            conciliaList = drugList.conciliaList(concilia_drugs, [])

    if disable_solution_tab:
        pSolution = []
    else:
        pSolution = drugList.getDrugType([], ["Soluções"])

    pInfusion = drugList.getInfusionList()

    pProcedures = drugList.getDrugType([], ["Proced/Exames"])

    pDiet = drugList.getDrugType([], ["Dietas"])

    drugList.sumAlerts()

    if aggDate:
        headers = buildHeaders(headers, pDrugs, pSolution, pProcedures)

        if is_cpoe:
            pDrugs = drugList.cpoeDrugs(pDrugs, idPrescription)
            pSolution = drugList.cpoeDrugs(pSolution, idPrescription)
            pProcedures = drugList.cpoeDrugs(pProcedures, idPrescription)
            pDiet = drugList.cpoeDrugs(pDiet, idPrescription)

    pIntervention = [
        i
        for i in interventions
        if int(i["id"]) == 0 and int(i["idPrescription"]) == prescription[0].id
    ]

    _log_perf(start_date, "ADDITIONAL QUERIES")

    return {
        "status": "success",
        "data": {
            "idPrescription": str(prescription[0].id),
            "idSegment": prescription[0].idSegment,
            "segmentName": prescription[5],
            "idPatient": str(prescription[0].idPatient),
            "idHospital": prescription[0].idHospital,
            "name": prescription[0].admissionNumber,
            "agg": prescription[0].agg,
            "prescriptionAggId": gen_agg_id(
                admission_number=prescription[0].admissionNumber,
                id_segment=prescription[0].idSegment,
                pdate=prescription[0].date,
            ),
            "concilia": prescription[0].concilia,
            "conciliaList": conciliaList,
            "admissionNumber": prescription[0].admissionNumber,
            "admissionDate": (
                patient.admissionDate.isoformat() if patient.admissionDate else None
            ),
            "birthdate": patient.birthdate.isoformat() if patient.birthdate else None,
            "gender": patient.gender,
            "height": patientHeight,
            "weight": patientWeight,
            "dialysis": patient.dialysis,
            "patient": {"lactating": patient.lactating, "pregnant": patient.pregnant},
            "observation": prescription[6],
            "notes": prescription[7],
            "alert": prescription[8],
            "alertExpire": (
                patient.alertExpire.isoformat() if patient.alertExpire else None
            ),
            "age": age,
            "weightUser": bool(patient.user),
            "weightDate": patientWeightDate.isoformat() if patientWeightDate else None,
            "dischargeDate": (
                patient.dischargeDate.isoformat() if patient.dischargeDate else None
            ),
            "dischargeReason": patient.dischargeReason,
            "bed": prescription[0].bed,
            "record": prescription[0].record,
            "class": random.choice(["green", "yellow", "red"]),
            "skinColor": patient.skinColor,
            "department": prescription[4],
            "lastDepartment": lastDept[0] if lastDept else None,
            "patientScore": "High",
            "date": prescription[0].date.isoformat(),
            "expire": (
                prescription[0].expire.isoformat() if prescription[0].expire else None
            ),
            "prescription": pDrugs,
            "solution": pSolution,
            "procedures": pProcedures,
            "infusion": pInfusion,
            "diet": pDiet,
            "interventions": interventions,
            "alertExams": alertExams,
            "exams": examsJson[:10],
            "status": prescription[0].status,
            "prescriber": prescription[9],
            "headers": headers,
            "intervention": pIntervention[0] if len(pIntervention) else None,
            "prevIntervention": getPrevIntervention(
                interventions, prescription[0].date
            ),
            "existIntervention": getExistIntervention(
                interventions, prescription[0].date
            ),
            "clinicalNotes": cn_count,
            "complication": cn_stats.get("complication", 0),
            "notesSigns": strNone(notesSigns[0]) if notesSigns else "",
            "notesSignsDate": notesSigns[1].isoformat() if notesSigns else None,
            "notesInfo": strNone(notesInfo[0]) if notesInfo else "",
            "notesInfoDate": notesInfo[1].isoformat() if notesInfo else None,
            "notesAllergies": notesAllergies,
            "notesAllergiesDate": notesAllergies[0]["date"] if notesAllergies else None,
            "notesDialysis": notesDialysis,
            "notesDialysisDate": notesDialysis[0]["date"] if notesDialysis else None,
            "clinicalNotesStats": cn_stats,
            "alertStats": drugList.alertStats,
            "features": prescription[0].features,
            "isBeingEvaluated": prescription_service.is_being_evaluated(
                prescription[0].features
            ),
            "user": prescription[10],
            "userId": prescription[0].user,
            "insurance": prescription[11],
            "formTemplate": formTemplate,
            "admissionReports": admission_reports,
            "admissionReportsInternal": admission_reports_internal,
            "review": {
                "reviewed": reviewed,
                "reviewedAt": reviewed_at,
                "reviewedBy": reviewed_by,
            },
        },
    }, status.HTTP_200_OK


@app_pres.route("/prescriptions/<int:idPrescription>", methods=["PUT"])
@jwt_required()
def setPrescriptionData(idPrescription):
    data = request.get_json()
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ["TZ"] = "America/Sao_Paulo"

    p = db.session.query(Prescription).filter(Prescription.id == idPrescription).first()
    if p is None:
        return {
            "status": "error",
            "message": "Prescrição Inexistente!",
        }, status.HTTP_400_BAD_REQUEST

    if not data_authorization_service.has_segment_authorization(
        id_segment=p.idSegment, user=user
    ):
        return {
            "status": "error",
            "message": "Usuário não autorizado neste segmento",
        }, status.HTTP_401_UNAUTHORIZED

    if "notes" in data.keys():
        p.notes = data.get("notes", None)
        p.notes_at = datetime.today()

        audit = PrescriptionAudit()
        audit.auditType = PrescriptionAuditTypeEnum.UPSERT_CLINICAL_NOTES.value
        audit.admissionNumber = p.admissionNumber
        audit.idPrescription = p.id
        audit.prescriptionDate = p.date
        audit.idDepartment = p.idDepartment
        audit.idSegment = p.idSegment
        audit.totalItens = 0
        audit.agg = p.agg
        audit.concilia = p.concilia
        audit.bed = p.bed
        audit.extra = {"text": data.get("notes", None)}
        audit.createdAt = datetime.today()
        audit.createdBy = user.id
        db.session.add(audit)

    if "concilia" in data.keys():
        concilia = data.get("concilia", "s")
        p.concilia = str(concilia)[:1]

    p.user = user.id

    return tryCommit(db, escape_html(str(idPrescription)), user.permission())


@app_pres.route("/prescriptions/status", methods=["POST"])
@jwt_required()
def setPrescriptionStatus():
    data = request.get_json()
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ["TZ"] = "America/Sao_Paulo"

    id_prescription = data.get("idPrescription", None)
    p_status = (
        escape_html(data.get("status", None))
        if data.get("status", None) != None
        else None
    )
    evaluation_time = data.get("evaluationTime", None)
    alerts = data.get("alerts", [])
    fast_check = data.get("fastCheck", False)

    try:
        result = prescription_service.check_prescription(
            idPrescription=id_prescription,
            p_status=p_status,
            user=user,
            evaluation_time=evaluation_time,
            alerts=alerts,
            fast_check=fast_check,
        )
    except ValidationError as e:
        return {
            "status": "error",
            "message": str(e),
            "code": e.code,
        }, e.httpStatus

    return tryCommit(db, result, user.permission())


@app_pres.route("/static/prescriptions/status", methods=["POST"])
@jwt_required()
def static_prescription_status():
    data = request.get_json()
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ["TZ"] = "America/Sao_Paulo"

    id_prescription = data.get("idPrescription", None)
    p_status = (
        escape_html(data.get("status", None))
        if data.get("status", None) != None
        else None
    )
    id_origin_user = data.get("idOriginUser", None)

    if not permission_service.is_service_user(user):
        return {
            "status": "error",
            "message": "usuário serviço inválido",
            "code": "invalid",
        }, status.HTTP_401_UNAUTHORIZED

    origin_user = (
        db.session.query(User)
        .filter(User.schema == user.schema)
        .filter(User.external == id_origin_user)
        .filter(User.active == True)
        .first()
    )

    if not origin_user:
        return {
            "status": "error",
            "message": "usuário origem inválido",
            "code": "invalid",
        }, status.HTTP_400_BAD_REQUEST

    try:
        result = prescription_service.check_prescription(
            idPrescription=id_prescription,
            p_status=p_status,
            user=origin_user,
            evaluation_time=0,
            alerts=[],
            service_user=True,
        )
    except ValidationError as e:
        return {
            "status": "error",
            "message": str(e),
            "code": e.code,
        }, e.httpStatus

    return tryCommit(db, result, origin_user.permission())


@app_pres.route("/prescriptions/review", methods=["POST"])
@jwt_required()
def review_prescription():
    data = request.get_json()
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ["TZ"] = "America/Sao_Paulo"

    id_prescription = data.get("idPrescription", None)
    evaluation_time = data.get("evaluationTime", None)
    review_type = data.get("reviewType", None)

    try:
        result = prescription_service.review_prescription(
            idPrescription=id_prescription,
            evaluation_time=evaluation_time,
            review_type=review_type,
            user=user,
        )
    except ValidationError as e:
        return {
            "status": "error",
            "message": str(e),
            "code": e.code,
        }, e.httpStatus

    return tryCommit(db, result, user.permission())


@app_pres.route("/prescriptions/drug/<int:idPrescriptionDrug>/period", methods=["GET"])
@jwt_required()
def getDrugPeriod(idPrescriptionDrug):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    is_cpoe = user.cpoe()

    future = request.args.get("future", None)
    results = [{1: []}]

    if idPrescriptionDrug != 0:
        results, admissionHistory = PrescriptionDrug.findByPrescriptionDrug(
            idPrescriptionDrug, future, is_cpoe=is_cpoe
        )
    else:
        results[0][1].append("Intervenção no paciente não tem medicamento associado.")

    if future and len(results[0][1]) == 0:
        if admissionHistory:
            results[0][1].append("Não há prescrição posterior para esse Medicamento")
        else:
            results[0][1].append("Não há prescrição posterior para esse Paciente")

    if is_cpoe and not future:
        periodList = []

        for i, p in enumerate(results):
            period = p[0]

            period = period.replace("33x", "SNx")
            period = period.replace("44x", "ACMx")
            period = period.replace("55x", "CONTx")
            period = period.replace("66x", "AGORAx")
            period = period.replace("99x", "N/Dx")
            periodList.append(period)
    else:
        periodList = results[0][1]

        for i, p in enumerate(periodList):
            p = p.replace("33x", "SNx")
            p = p.replace("44x", "ACMx")
            p = p.replace("55x", "CONTx")
            p = p.replace("66x", "AGORAx")
            p = p.replace("99x", "N/Dx")
            periodList[i] = p

    return {"status": "success", "data": periodList}, status.HTTP_200_OK


# TODO: REFACTOR
@app_pres.route("/prescriptions/drug/<int:idPrescriptionDrug>", methods=["PUT"])
@jwt_required()
def setPrescriptionDrugNote(idPrescriptionDrug):
    data = request.get_json()
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ["TZ"] = "America/Sao_Paulo"

    drug = (
        db.session.query(PrescriptionDrug)
        .filter(PrescriptionDrug.id == idPrescriptionDrug)
        .first()
    )
    if drug is None:
        return {
            "status": "error",
            "message": "Prescrição  Inexistente!",
        }, status.HTTP_400_BAD_REQUEST

    if not data_authorization_service.has_segment_authorization(
        id_segment=drug.idSegment, user=user
    ):
        return {
            "status": "error",
            "message": "Usuário não autorizado neste segmento",
        }, status.HTTP_401_UNAUTHORIZED

    if "notes" in data:
        notes = data.get("notes", None)
        idDrug = data.get("idDrug", None)
        admissionNumber = data.get("admissionNumber", None)
        note = Notes.query.get((0, idPrescriptionDrug))
        newObs = False

        if note is None:
            newObs = True
            note = Notes()
            note.idPrescriptionDrug = idPrescriptionDrug
            note.idOutlier = 0

        note.idDrug = idDrug
        note.admissionNumber = admissionNumber
        note.notes = notes
        note.update = datetime.today()
        note.user = user.id

        if newObs:
            db.session.add(note)

    if "form" in data:
        drug.form = data.get("form", None)
        drug.update = datetime.today()
        drug.user = user.id

    return tryCommit(db, escape_html(str(idPrescriptionDrug)), user.permission())


@app_pres.route("/prescriptions/drug/form", methods=["PUT"])
@jwt_required()
def update_form():
    data = request.get_json()
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ["TZ"] = "America/Sao_Paulo"

    try:
        prescription_drug_service.update_pd_form(data, user)
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, True, user.permission())


@app_pres.route("/prescriptions/<int:idPrescription>/update", methods=["GET"])
@jwt_required()
def getPrescriptionUpdate(idPrescription):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    try:
        prescription_service.recalculate_prescription(
            id_prescription=idPrescription, user=user
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, escape_html(str(idPrescription)))


@app_pres.route("/prescriptions/search", methods=["GET"])
@jwt_required()
def search_prescriptions():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    search_key = request.args.get("term", None)

    if search_key == None:
        return {
            "status": "error",
            "message": "Missing search param",
        }, status.HTTP_400_BAD_REQUEST

    results = prescription_service.search(search_key)

    list = []

    for p in results:
        list.append(
            {
                "idPrescription": str(p[0].id),
                "admissionNumber": p[0].admissionNumber,
                "date": p[0].date.isoformat() if p[0].date else None,
                "status": p[0].status,
                "agg": p[0].agg,
                "concilia": p[0].concilia,
                "birthdate": p[1].isoformat() if p[1] else None,
                "gender": p[2],
                "department": p[3],
                "admissionDate": p[4].isoformat() if p[4] else None,
            }
        )

    return {
        "status": "success",
        "data": list,
    }, status.HTTP_200_OK


@app_pres.route("/prescriptions/start-evaluation", methods=["POST"])
@jwt_required()
def start_evaluation():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    data = request.get_json()

    try:
        result = prescription_service.start_evaluation(
            id_prescription=data.get("idPrescription", None), user=user
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, result)


# remove after solving circular dependency
def _get_last_agg_prescription(admission_number) -> Prescription:
    return (
        db.session.query(Prescription)
        .filter(Prescription.admissionNumber == admission_number)
        .filter(Prescription.agg == True)
        .filter(Prescription.concilia == None)
        .filter(Prescription.idSegment != None)
        .order_by(desc(Prescription.date))
        .first()
    )
