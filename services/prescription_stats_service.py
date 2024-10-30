import logging
from datetime import datetime, date
from flask_sqlalchemy.session import Session
from sqlalchemy import text

from decorators.has_permission_decorator import has_permission, Permission
from exception.validation_error import ValidationError
from models.main import db, User, dbSession
from models.prescription import (
    Prescription,
    Patient,
    PrescriptionDrug,
)
from models.segment import Exams
from models.enums import (
    MemoryEnum,
)
from utils.drug_list import DrugList
from services import (
    memory_service,
    intervention_service,
    clinical_notes_service,
    alert_interaction_service,
    alert_service,
    feature_service,
)
from utils import prescriptionutils, dateutils, status


@has_permission(Permission.READ_STATIC)
def get_prescription_stats(
    idPrescription: int,
    schema: str,
    user_context: User = None,
):
    _set_schema(schema)

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
    patientHeight = None

    if patient is None:
        patient = Patient()
        patient.idPatient = prescription[0].idPatient
        patient.admissionNumber = prescription[0].admissionNumber

    if patient.weight != None:
        patientWeight = patient.weight
        patientHeight = patient.height

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
    _log_perf(start_date, "GET DRUGS AND INTERVENTIONS")

    # get memory configurations
    start_date = datetime.now()
    memory_itens = memory_service.get_by_kind(
        [
            MemoryEnum.MAP_SCHEDULES_FASTING.value,
        ]
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

    _log_perf(start_date, "GET CLINICAL NOTES")

    start_date = datetime.now()

    exams = Exams.findLatestByAdmission(
        patient, prescription[0].idSegment, prevEx=False
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

    pDrugs = drugList.getDrugType([], ["Medicamentos"])
    pSolution = drugList.getDrugType([], ["Soluções"])
    pProcedures = drugList.getDrugType([], ["Proced/Exames"])
    pDiet = drugList.getDrugType([], ["Dietas"])

    drugList.sumAlerts()

    p_data = {
        "idPrescription": str(prescription[0].id),
        "agg": prescription[0].agg,
        "concilia": prescription[0].concilia,
        "admissionNumber": prescription[0].admissionNumber,
        "dischargeDate": (
            patient.dischargeDate.isoformat() if patient.dischargeDate else None
        ),
        "date": prescription[0].date.isoformat(),
        "expire": (
            prescription[0].expire.isoformat() if prescription[0].expire else None
        ),
        "prescription": pDrugs,
        "solution": pSolution,
        "procedures": pProcedures,
        "diet": pDiet,
        "interventions": interventions,
        "alertExams": alertExams,
        "status": prescription[0].status,
        "clinicalNotes": cn_count,
        "complication": cn_stats.get("complication", 0),
        "clinicalNotesStats": cn_stats,
        "alertStats": drugList.alertStats,
    }

    return prescriptionutils.getFeatures(
        result=p_data,
        agg_date=prescription[0].date if prescription[0].agg else None,
        intervals_for_agg_date=prescription[0].agg,
    )


def _log_perf(start_date, section):
    end_date = datetime.now()
    logging.basicConfig()
    logger = logging.getLogger("noharm.backend")

    logger.debug(f"PERF {section}: {(end_date-start_date).total_seconds()}")


def _set_schema(schema):
    db_session = Session(db)
    result = db_session.execute(
        text("SELECT schema_name FROM information_schema.schemata")
    )

    schemaExists = False
    for r in result:
        if r[0] == schema:
            schemaExists = True

    if not schemaExists:
        raise ValidationError(
            "Schema Inexistente", "errors.invalidSchema", status.HTTP_400_BAD_REQUEST
        )

    db_session.close()

    dbSession.setSchema(schema)
