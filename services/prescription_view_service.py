"""Service: dedicated to prescription view data"""

from datetime import datetime, date
from sqlalchemy import desc, and_, func
from sqlalchemy.dialects.postgresql import INTERVAL

from decorators.has_permission_decorator import has_permission, Permission
from decorators.timed_decorator import timed
from exception.validation_error import ValidationError
from models.main import db, User
from models.prescription import (
    Prescription,
    Patient,
    PrescriptionAudit,
)
from models.appendix import Department, ICDTable
from models.segment import Segment
from models.enums import (
    MemoryEnum,
    FeatureEnum,
    PrescriptionReviewTypeEnum,
    PrescriptionAuditTypeEnum,
    AppFeatureFlagEnum,
    DrugTypeEnum,
)
from repository import (
    prescription_view_repository,
    patient_repository,
    clinical_notes_repository,
)
from services import (
    prescription_service,
    memory_service,
    patient_service,
    intervention_service,
    clinical_notes_service,
    alert_interaction_service,
    alert_protocol_service,
    alert_service,
    feature_service,
    exams_service,
)
from utils.drug_list import DrugList
from utils import prescriptionutils, dateutils, status


@has_permission(Permission.READ_PRESCRIPTION)
def route_get_prescription(id_prescription: int, user_context: User = None):
    return _internal_get_prescription(
        id_prescription=id_prescription, is_complete=True, user_context=user_context
    )


@has_permission(Permission.READ_STATIC)
def static_get_prescription(id_prescription: int, user_context: User = None):
    return _internal_get_prescription(
        id_prescription=id_prescription, is_complete=False, user_context=user_context
    )


def _internal_get_prescription(
    id_prescription: int,
    user_context: User,
    is_complete=False,
):
    prescription, patient, department, segment, prescription_user, icd = (
        _get_prescription_data(id_prescription=id_prescription)
    )

    config_data = _get_configs(prescription=prescription, patient=patient)

    interventions = _get_interventions(
        admission_number=prescription.admissionNumber,
        config_data=config_data,
        concilia=prescription.concilia,
    )

    cn_data = _get_clinical_notes_stats(
        prescription=prescription,
        patient=patient,
        config_data=config_data,
        user_context=user_context,
        is_complete=is_complete,
    )

    exam_data = _get_exams(
        patient=patient,
        prescription=prescription,
        config_data=config_data,
        is_complete=is_complete,
        user_context=user_context,
    )

    last_dept = _get_last_dept(prescription=prescription, is_complete=is_complete)

    drug_list = _get_drug_list(
        prescription=prescription,
        patient=patient,
        config_data=config_data,
        user_context=user_context,
    )

    alerts_data = _get_alerts(
        prescription=prescription,
        drug_list=drug_list,
        patient=patient,
        config_data=config_data,
        exam_data=exam_data,
        cn_data=cn_data,
        user_context=user_context,
    )

    drug_data = _get_drug_data(
        drugs=drug_list,
        prescription=prescription,
        patient=patient,
        interventions=interventions,
        alerts_data=alerts_data,
        exams_data=exam_data,
        config_data=config_data,
        is_complete=is_complete,
        user_context=user_context,
    )

    review_data = _get_review_data(prescription=prescription, is_complete=is_complete)

    return _format(
        prescription=prescription,
        patient=patient,
        department=department,
        segment=segment,
        prescription_user=prescription_user,
        config_data=config_data,
        drug_data=drug_data,
        interventions=interventions,
        exams_data=exam_data,
        last_dept=last_dept,
        cn_data=cn_data,
        review_data=review_data,
        alerts_data=alerts_data,
        icd=icd,
    )


@timed()
def _get_last_dept(prescription: Prescription, is_complete: bool):
    if is_complete:
        return (
            db.session.query(Department.name)
            .select_from(Prescription)
            .outerjoin(
                Department,
                and_(
                    Department.id == Prescription.idDepartment,
                    Department.idHospital == Prescription.idHospital,
                ),
            )
            .filter(Prescription.admissionNumber == prescription.admissionNumber)
            .filter(Prescription.id < prescription.id)
            .filter(
                Prescription.date
                > (func.date(prescription.date) - func.cast("1 month", INTERVAL))
            )
            .order_by(desc(Prescription.id))
            .first()
        )

    return None


@timed()
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


@timed()
def _build_headers(
    prescription: Prescription,
    config_data: dict,
    pDrugs: dict,
    pSolution: dict,
    pProcedures: dict,
    user_context: User,
):
    headers = prescription_view_repository.get_headers(
        admissionNumber=prescription.admissionNumber,
        aggDate=prescription.date,
        idSegment=prescription.idSegment,
        is_pmc=config_data["is_pmc"],
        is_cpoe=config_data["is_cpoe"],
        schema=user_context.schema,
    )

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
                "alertExams": 0,
                "complication": 0,
            }
        )
        headers[pid]["solutions"] = prescriptionutils.getFeatures(
            {
                "prescription": [],
                "solution": solutions,
                "procedures": [],
                "interventions": solutionsInterv,
                "alertExams": 0,
                "complication": 0,
            }
        )
        headers[pid]["procedures"] = prescriptionutils.getFeatures(
            {
                "prescription": [],
                "solution": [],
                "procedures": procedures,
                "interventions": proceduresInterv,
                "alertExams": 0,
                "complication": 0,
            }
        )

    return headers


def _get_prev_intervention(interventions, dtPrescription, admission_number: int):
    """check if patient has previous pending intervention"""
    result = False
    for i in interventions:
        if (
            int(i["id"]) == 0
            and i["status"] == "s"
            and i["admissionNumber"] == admission_number
            and datetime.fromisoformat(i["date"])
            < datetime(
                dtPrescription.year, dtPrescription.month, dtPrescription.day, 0, 0
            )
        ):
            result = True
    return result


def _get_exist_intervention(interventions, dtPrescription, admission_number: int):
    """check if patient has previous intervention"""

    result = False
    for i in interventions:
        if (
            int(i["id"]) == 0
            and i["admissionNumber"] == admission_number
            and datetime.fromisoformat(i["date"])
            < datetime(
                dtPrescription.year, dtPrescription.month, dtPrescription.day, 0, 0
            )
        ):
            result = True
    return result


@timed()
def _get_prescription_data(
    id_prescription: int,
) -> tuple[Prescription, Patient, Department, Segment, User]:
    data = (
        db.session.query(Prescription, Patient, Department, Segment, User, ICDTable)
        .outerjoin(Patient, Patient.admissionNumber == Prescription.admissionNumber)
        .outerjoin(ICDTable, Patient.id_icd == ICDTable.id_str)
        .outerjoin(
            Department,
            and_(
                Department.id == Prescription.idDepartment,
                Department.idHospital == Prescription.idHospital,
            ),
        )
        .outerjoin(Segment, Segment.id == Prescription.idSegment)
        .outerjoin(User, Prescription.user == User.id)
        .filter(Prescription.id == id_prescription)
        .first()
    )

    if data is None:
        raise ValidationError(
            "Prescrição inexistente",
            "errors.invalidRecord",
            status.HTTP_400_BAD_REQUEST,
        )

    prescription: Prescription = data[0]
    patient: Patient = data[1]
    department: Department = data[2]
    segment: Segment = data[3]
    prescription_user: User = data[4]
    icd: ICDTable = data[5]

    if patient is None:
        patient = Patient()
        patient.idPatient = prescription.idPatient
        patient.admissionNumber = prescription.admissionNumber

    return prescription, patient, department, segment, prescription_user, icd


@timed()
def _get_configs(prescription: Prescription, patient: Patient):
    data = {}

    # memory
    memory_itens = memory_service.get_by_kind(
        [
            MemoryEnum.MAP_SCHEDULES_FASTING.value,
            MemoryEnum.PRESMED_FORM.value,
            MemoryEnum.ADMISSION_REPORTS.value,
            MemoryEnum.ADMISSION_REPORTS_INTERNAL.value,
            MemoryEnum.FEATURES.value,
        ]
    )
    data["schedules_fasting"] = memory_itens.get(
        MemoryEnum.MAP_SCHEDULES_FASTING.value, []
    )
    data["form_template"] = memory_itens.get(MemoryEnum.PRESMED_FORM.value, None)
    data["admission_reports"] = memory_itens.get(
        MemoryEnum.ADMISSION_REPORTS.value, None
    )
    data["admission_reports_internal"] = memory_itens.get(
        MemoryEnum.ADMISSION_REPORTS_INTERNAL.value, []
    )
    data["is_pmc"] = FeatureEnum.PRIMARY_CARE.value in memory_itens.get(
        MemoryEnum.FEATURES.value, []
    )
    data["disable_solution_tab"] = (
        FeatureEnum.DISABLE_SOLUTION_TAB.value
        in memory_itens.get(MemoryEnum.FEATURES.value, [])
    )

    data["is_cpoe"] = feature_service.is_cpoe()

    # patient data
    data["weight"] = patient.weight if patient.weight else None
    data["weight_date"] = patient.weightDate if patient.weightDate else None
    data["height"] = patient.height if patient.height else None
    data["age"] = dateutils.data2age(
        patient.birthdate.isoformat() if patient.birthdate else date.today().isoformat()
    )

    if data["weight"] == None:
        patient_previous_data = patient_service.get_patient_weight(patient.idPatient)

        if patient_previous_data != None:
            data["weight"] = (
                patient_previous_data.weight if patient_previous_data.weight else None
            )
            data["weight_date"] = (
                patient_previous_data.weightDate
                if patient_previous_data.weightDate
                else None
            )
            data["height"] = (
                patient_previous_data.height if patient_previous_data.height else None
            )

    # previous admissions
    data["previous_admissions"] = patient_repository.get_previous_admissions(
        admission_number=prescription.admissionNumber,
        id_patient=patient.idPatient,
        limit=2,
    )

    return data


@timed()
def _get_interventions(admission_number: int, config_data: dict, concilia: str):
    if config_data["previous_admissions"]:
        # get interventions from current and previous admissions
        interventions = intervention_service.get_interventions(
            admission_number_list=config_data["previous_admissions"]
        )
    else:
        interventions = intervention_service.get_interventions(
            admissionNumber=admission_number
        )

    if not concilia:
        return interventions

    # if conciliation: show interventions for active itens only
    return [i for i in interventions if i.get("suspendedDate") is None]


@timed()
def _get_clinical_notes_stats(
    prescription: Prescription,
    patient: Patient,
    config_data: dict,
    is_complete: bool,
    user_context: User,
):
    is_cache_active = feature_service.has_feature_flag(
        flag=AppFeatureFlagEnum.REDIS_CACHE
    )

    cn_stats = clinical_notes_repository.get_admission_stats(
        admission_number=prescription.admissionNumber,
        user_context=user_context,
        cache=is_cache_active,
    )

    if cn_stats and (config_data["age"] <= 9 or patient.gender == "M"):
        cn_stats["pregnant"] = 0

    cn_count = 1
    if config_data["is_pmc"]:
        cn_count = clinical_notes_service.get_count(
            admission_number=prescription.admissionNumber,
            admission_date=patient.admissionDate,
        )

    signs_data = {}
    infos_data = {}
    allergies_data = []
    dialysis_data = []

    if is_complete:
        if cn_stats.get("signs", 0) != 0:
            signs_data = clinical_notes_repository.get_signs(
                admission_number=prescription.admissionNumber,
                user_context=user_context,
                cache=is_cache_active,
            )

        infos_data = clinical_notes_repository.get_infos(
            admission_number=prescription.admissionNumber,
            user_context=user_context,
            cache=is_cache_active,
        )

        allergies = clinical_notes_repository.get_allergies(
            admission_number=prescription.admissionNumber,
            admission_date=patient.admissionDate,
            user_context=user_context,
            cache=is_cache_active,
        )
        db_allergies = patient_service.get_patient_allergies(patient.idPatient)

        allergies_data += allergies

        for a in db_allergies:
            if a[1] and a[1].strip():
                allergies_data.append(
                    {"date": dateutils.to_iso(a[0]), "text": a[1], "source": "pep"}
                )

        dialysis_data = clinical_notes_repository.get_dialysis(
            admission_number=prescription.admissionNumber,
            user_context=user_context,
            cache=is_cache_active,
        )

    return {
        "cn_stats": cn_stats,
        "cn_count": cn_count,
        "notes": {
            "signs": signs_data,
            "infos": infos_data,
            "allergies": allergies_data,
            "dialysis": dialysis_data,
        },
    }


@timed()
def _get_exams(
    patient: Patient,
    prescription: Prescription,
    config_data: dict,
    is_complete: bool,
    user_context: User,
):
    is_cache_active = feature_service.has_feature_flag(
        flag=AppFeatureFlagEnum.REDIS_CACHE_EXAMS
    )

    is_cache_hybrid_active = feature_service.has_feature_flag(
        flag=AppFeatureFlagEnum.REDIS_CACHE_EXAMS_HYBRID
    )

    exams = exams_service.find_latest_exams(
        patient=patient,
        idSegment=prescription.idSegment,
        schema=user_context.schema,
        add_previous_exams=is_complete,
        cache=is_cache_active,
        cache_hybrid=is_cache_hybrid_active,
        is_complete=is_complete,
    )

    examsJson = []
    alertExams = 0
    for e in exams:
        examsJson.append({"key": e, "value": exams[e]})
        alertExams += int(exams[e]["alert"])

    exams = dict(
        exams,
        **{
            "age": config_data["age"],
            "weight": config_data["weight"],
            "height": config_data["height"],
        },
    )

    return {"exams": exams, "exams_card": examsJson[:20], "alerts": alertExams}


@timed()
def _get_drug_list(
    prescription: Prescription, patient: Patient, config_data: dict, user_context: User
):
    return prescription_view_repository.find_drugs_by_prescription(
        idPrescription=prescription.id,
        admissionNumber=patient.admissionNumber,
        schema=user_context.schema,
        aggDate=prescription.date if prescription.agg else None,
        idSegment=prescription.idSegment,
        is_cpoe=config_data.get("is_cpoe"),
        is_pmc=config_data.get("is_pmc"),
    )


@timed()
def _get_alerts(
    prescription: Prescription,
    drug_list,
    patient: Patient,
    config_data: dict,
    exam_data: dict,
    cn_data: dict,
    user_context: User,
):
    relations = alert_interaction_service.find_relations(
        drug_list=drug_list,
        is_cpoe=config_data["is_cpoe"],
        id_patient=patient.idPatient,
    )

    alerts = alert_service.find_alerts(
        drug_list=drug_list,
        exams=exam_data["exams"],
        dialisys=patient.dialysis,
        pregnant=patient.pregnant,
        lactating=patient.lactating,
        schedules_fasting=config_data["schedules_fasting"],
        cn_data=cn_data,
    )

    protocols = alert_protocol_service.find_protocols(
        drug_list=drug_list,
        exams=exam_data["exams"],
        prescription=prescription,
        patient=patient,
        user_context=user_context,
        cn_stats=cn_data["cn_stats"],
    )

    return {"relations": relations, "alerts": alerts, "protocols": protocols}


@timed()
def _get_drug_data(
    drugs,
    prescription: Prescription,
    patient: Patient,
    interventions,
    alerts_data: dict,
    exams_data: dict,
    config_data: dict,
    is_complete: bool,
    user_context: User,
):
    drug_list = DrugList(
        drugList=drugs,
        interventions=interventions,
        relations=alerts_data["relations"],
        exams=exams_data["exams"],
        agg=prescription.agg,
        dialysis=patient.dialysis,
        alerts=alerts_data["alerts"],
        is_cpoe=config_data["is_cpoe"],
        admission_number=prescription.admissionNumber,
    )

    if config_data["disable_solution_tab"]:
        p_drugs = drug_list.getDrugType([], ["Medicamentos", "Soluções"])
        p_solution = []
    else:
        p_drugs = drug_list.getDrugType([], ["Medicamentos"])
        p_solution = drug_list.getDrugType([], ["Soluções"])

    p_procedures = drug_list.getDrugType([], ["Proced/Exames"])
    p_diet = drug_list.getDrugType([], ["Dietas"])
    p_infusion = drug_list.getInfusionList()

    drug_list.sumAlerts()

    headers = []
    if prescription.agg:
        headers = _build_headers(
            prescription=prescription,
            config_data=config_data,
            pDrugs=p_drugs,
            pSolution=p_solution,
            pProcedures=p_procedures,
            user_context=user_context,
        )

        if config_data["is_cpoe"]:
            p_drugs = drug_list.cpoeDrugs(p_drugs, prescription.id)
            p_solution = drug_list.cpoeDrugs(p_solution, prescription.id)
            p_procedures = drug_list.cpoeDrugs(p_procedures, prescription.id)
            p_diet = drug_list.cpoeDrugs(p_diet, prescription.id)

    # concilia data
    concilia_list = []
    if prescription.concilia:
        p_drugs = drug_list.changeDrugName(p_drugs)
        last_agg_prescription = _get_last_agg_prescription(patient.admissionNumber)
        if last_agg_prescription != None:
            concilia_drugs = prescription_view_repository.find_drugs_by_prescription(
                idPrescription=last_agg_prescription.id,
                admissionNumber=patient.admissionNumber,
                schema=user_context.schema,
                aggDate=last_agg_prescription.date,
                idSegment=None,
                is_cpoe=config_data["is_cpoe"],
            )
            concilia_list = drug_list.conciliaList(concilia_drugs, [])

        if is_complete and concilia_list:
            p_drugs = drug_list.infer_substance(pDrugs=p_drugs)

    return {
        "drug_list": drug_list,
        "headers": headers,
        "infusion": p_infusion,
        "concilia_list": concilia_list,
        "source": {
            DrugTypeEnum.DRUG.value: p_drugs,
            DrugTypeEnum.SOLUTION.value: p_solution,
            DrugTypeEnum.PROCEDURE.value: p_procedures,
            DrugTypeEnum.DIET.value: p_diet,
        },
    }


@timed()
def _get_review_data(prescription: Prescription, is_complete: bool):
    reviewed = False
    reviewed_by = None
    reviewed_at = None
    if prescription.reviewType == PrescriptionReviewTypeEnum.REVIEWED.value:
        reviewed = True

        if is_complete:
            reviewed_log = (
                db.session.query(PrescriptionAudit, User)
                .join(User, PrescriptionAudit.createdBy == User.id)
                .filter(PrescriptionAudit.idPrescription == prescription.id)
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

    return {
        "reviewed": reviewed,
        "reviewedAt": reviewed_at,
        "reviewedBy": reviewed_by,
    }


@timed()
def _format(
    prescription: Prescription,
    patient: Patient,
    segment: Segment,
    department: Department,
    prescription_user: User,
    config_data: dict,
    drug_data: dict,
    interventions,
    exams_data: dict,
    last_dept,
    cn_data: dict,
    review_data: dict,
    alerts_data: dict,
    icd: ICDTable,
):
    return {
        # prescription
        "idPrescription": str(prescription.id),
        "idSegment": prescription.idSegment,
        "idPatient": str(prescription.idPatient),
        "idHospital": prescription.idHospital,
        "name": prescription.admissionNumber,
        "agg": prescription.agg,
        "prescriptionAggId": prescriptionutils.gen_agg_id(
            admission_number=prescription.admissionNumber,
            id_segment=prescription.idSegment,
            pdate=prescription.date,
        ),
        "concilia": prescription.concilia,
        "admissionNumber": prescription.admissionNumber,
        "notes": prescription.notes,
        "bed": prescription.bed,
        "record": prescription.record,
        "skinColor": patient.skinColor,
        "date": dateutils.to_iso(prescription.date),
        "expire": dateutils.to_iso(prescription.expire),
        "status": prescription.status,
        "prescriber": prescription.prescriber,
        "features": prescription.features,
        "user": prescription_user.name if prescription_user else None,
        "userId": prescription.user,
        "insurance": prescription.insurance,
        "idICD": icd.id_str if icd else None,
        "nameICD": icd.name if icd else None,
        # patient
        "admissionDate": dateutils.to_iso(patient.admissionDate),
        "birthdate": dateutils.to_iso(patient.birthdate),
        "gender": patient.gender,
        "height": config_data["height"],
        "weight": config_data["weight"],
        "age": config_data["age"],
        "weightUser": bool(patient.user),
        "weightDate": dateutils.to_iso(config_data["weight_date"]),
        "dialysis": patient.dialysis,
        "observation": patient.observation,
        "patient": {
            "lactating": patient.lactating,
            "pregnant": patient.pregnant,
            "tags": patient.tags,
        },
        "alert": patient.alert,
        "alertExpire": dateutils.to_iso(patient.alertExpire),
        "dischargeDate": dateutils.to_iso(patient.dischargeDate),
        "dischargeReason": patient.dischargeReason,
        "dischargeDateForecast": dateutils.to_iso(patient.dischargeDateForecast),
        "responsiblePhysician": patient.responsiblePhysician,
        # extra
        "segmentName": segment.description if segment else None,
        "department": department.name if department else None,
        "lastDepartment": last_dept[0] if last_dept else None,
        "patientScore": "High",
        "formTemplate": config_data["form_template"],
        "admissionReports": config_data["admission_reports"],
        "admissionReportsInternal": config_data["admission_reports_internal"],
        "isCpoe": config_data["is_cpoe"],
        # drugs
        "headers": drug_data["headers"],
        "alertStats": drug_data["drug_list"].alertStats,
        "prescription": drug_data["source"][DrugTypeEnum.DRUG.value],
        "solution": drug_data["source"][DrugTypeEnum.SOLUTION.value],
        "procedures": drug_data["source"][DrugTypeEnum.PROCEDURE.value],
        "diet": drug_data["source"][DrugTypeEnum.DIET.value],
        "infusion": drug_data["infusion"],
        "conciliaList": drug_data["concilia_list"],
        # interventions
        "interventions": interventions,
        "prevIntervention": _get_prev_intervention(
            interventions, prescription.date, prescription.admissionNumber
        ),
        "existIntervention": _get_exist_intervention(
            interventions, prescription.date, prescription.admissionNumber
        ),
        # exams
        "alertExams": exams_data["alerts"],
        "exams": exams_data["exams_card"],
        # clinical notes
        "clinicalNotes": cn_data["cn_count"],
        "clinicalNotesStats": cn_data["cn_stats"],
        "complication": cn_data["cn_stats"].get("complication", 0),
        "notesSigns": cn_data["notes"]["signs"].get("data", ""),
        "notesSignsId": cn_data["notes"]["signs"].get("id", None),
        "notesSignsDate": cn_data["notes"]["signs"].get("date", None),
        "notesSignsCache": cn_data["notes"]["signs"].get("cache", False),
        "notesInfo": cn_data["notes"]["infos"].get("data", ""),
        "notesInfoId": cn_data["notes"]["infos"].get("id", None),
        "notesInfoDate": cn_data["notes"]["infos"].get("date", None),
        "notesInfoCache": cn_data["notes"]["infos"].get("cache", False),
        "notesAllergies": cn_data["notes"]["allergies"],
        "notesAllergiesDate": (
            cn_data["notes"]["allergies"][0]["date"]
            if cn_data["notes"]["allergies"]
            else None
        ),
        "notesDialysis": cn_data["notes"]["dialysis"],
        "notesDialysisDate": (
            cn_data["notes"]["dialysis"][0]["date"]
            if cn_data["notes"]["dialysis"]
            else None
        ),
        # review
        "isBeingEvaluated": prescription_service.is_being_evaluated(
            prescription.features
        ),
        "review": review_data,
        "protocolAlerts": alerts_data.get("protocols", {}),
    }
