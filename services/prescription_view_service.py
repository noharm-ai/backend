import logging
import random
from datetime import datetime, date
from sqlalchemy import desc

from decorators.has_permission_decorator import has_permission, Permission
from exception.validation_error import ValidationError
from models.main import db, User
from models.prescription import (
    Prescription,
    Patient,
    PrescriptionDrug,
    PrescriptionAudit,
)
from models.segment import Exams
from models.enums import (
    MemoryEnum,
    FeatureEnum,
    PrescriptionReviewTypeEnum,
    PrescriptionAuditTypeEnum,
    AppFeatureFlagEnum,
)
from utils.drug_list import DrugList
from services import (
    prescription_service,
    memory_service,
    patient_service,
    intervention_service,
    clinical_notes_service,
    clinical_notes_queries_service,
    alert_interaction_service,
    alert_service,
    feature_service,
)
from utils import prescriptionutils, dateutils, status


@has_permission(Permission.READ_PRESCRIPTION)
def route_get_prescription(id_prescription: int, user_context: User):
    return internal_get_prescription(
        idPrescription=id_prescription, is_complete=True, user_context=user_context
    )


@has_permission(Permission.READ_STATIC)
def static_get_prescription(idPrescription: int, user_context: User):
    return internal_get_prescription(
        idPrescription=idPrescription, is_complete=False, user_context=user_context
    )


def internal_get_prescription(
    idPrescription: int,
    user_context: User,
    is_complete=False,
):
    start_date = datetime.now()

    prescription = Prescription.getPrescription(idPrescription)
    if prescription is None:
        raise ValidationError(
            "Prescrição inexistente",
            "errors.invalidRecord",
            status.HTTP_400_BAD_REQUEST,
        )

    is_cpoe = feature_service.is_cpoe()
    is_pmc = memory_service.has_feature("PRIMARYCARE")

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
        ref_date=prescription[0].date,
    )

    _log_perf(start_date, "GET PRESCRIPTION")

    start_date = datetime.now()
    drugs = PrescriptionDrug.findByPrescription(
        prescription[0].id,
        patient.admissionNumber,
        prescription[0].date if prescription[0].agg else None,
        prescription[0].idSegment,
        is_cpoe,
        is_pmc,
    )
    interventions = intervention_service.get_interventions(
        admissionNumber=patient.admissionNumber
    )
    headers = (
        Prescription.getHeaders(
            patient.admissionNumber,
            prescription[0].date,
            prescription[0].idSegment,
            is_pmc,
            is_cpoe,
        )
        if prescription[0].agg
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
            == prescriptionutils.gen_agg_id(
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

    notesSigns = {}
    notesInfo = {}
    notesAllergies = []
    notesDialysis = None

    if cn_count > 0 and is_complete:
        is_cache_active = memory_service.is_feature_active(
            AppFeatureFlagEnum.REDIS_CACHE
        )

        if cn_stats.get("signs", 0) != 0:
            notesSigns = clinical_notes_queries_service.get_signs(
                admission_number=prescription[0].admissionNumber,
                user_context=user_context,
                cache=is_cache_active,
            )

        notesInfo = clinical_notes_queries_service.get_infos(
            admission_number=prescription[0].admissionNumber,
            user_context=user_context,
            cache=is_cache_active,
        )
        allergies = clinical_notes_queries_service.get_allergies(
            admission_number=prescription[0].admissionNumber,
            admission_date=patient.admissionDate,
        )
        dialysis = clinical_notes_queries_service.get_dialysis(
            admission_number=prescription[0].admissionNumber
        )

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
    age = dateutils.data2age(
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
        prescription[0].agg,
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

    if prescription[0].agg:
        headers = _build_headers(headers, pDrugs, pSolution, pProcedures)

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
        "idPrescription": str(prescription[0].id),
        "idSegment": prescription[0].idSegment,
        "segmentName": prescription[5],
        "idPatient": str(prescription[0].idPatient),
        "idHospital": prescription[0].idHospital,
        "name": prescription[0].admissionNumber,
        "agg": prescription[0].agg,
        "prescriptionAggId": prescriptionutils.gen_agg_id(
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
        "prevIntervention": _get_prev_intervention(interventions, prescription[0].date),
        "existIntervention": _get_exist_intervention(
            interventions, prescription[0].date
        ),
        "clinicalNotes": cn_count,
        "complication": cn_stats.get("complication", 0),
        "notesSigns": notesSigns.get("data", ""),
        "notesSignsDate": notesSigns.get("date", None),
        "notesSignsCache": notesSigns.get("cache", False),
        "notesInfo": notesInfo.get("data", ""),
        "notesInfoDate": notesInfo.get("date", None),
        "notesInfoCache": notesInfo.get("cache", False),
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
    }


def _log_perf(start_date, section):
    end_date = datetime.now()
    logging.basicConfig()
    logger = logging.getLogger("noharm.backend")

    logger.debug(f"PERF {section}: {(end_date-start_date).total_seconds()}")


# TODO: refactor (duplicated)
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


def _build_headers(headers, pDrugs, pSolution, pProcedures):
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

        headers[pid]["drugs"] = prescriptionutils.getFeatures(
            {
                "prescription": drugs,
                "solution": [],
                "procedures": [],
                "interventions": drugsInterv,
                "alertExams": [],
                "complication": 0,
            }
        )
        headers[pid]["solutions"] = prescriptionutils.getFeatures(
            {
                "prescription": [],
                "solution": solutions,
                "procedures": [],
                "interventions": solutionsInterv,
                "alertExams": [],
                "complication": 0,
            }
        )
        headers[pid]["procedures"] = prescriptionutils.getFeatures(
            {
                "prescription": [],
                "solution": [],
                "procedures": procedures,
                "interventions": proceduresInterv,
                "alertExams": [],
                "complication": 0,
            }
        )

    return headers


def _get_prev_intervention(interventions, dtPrescription):
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


def _get_exist_intervention(interventions, dtPrescription):
    result = False
    for i in interventions:
        if int(i["id"]) == 0 and datetime.fromisoformat(i["date"]) < datetime(
            dtPrescription.year, dtPrescription.month, dtPrescription.day, 0, 0
        ):
            result = True
    return result
