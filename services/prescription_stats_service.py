from datetime import datetime, date

from decorators.has_permission_decorator import has_permission, Permission
from decorators.timed_decorator import timed
from exception.validation_error import ValidationError
from models.main import db
from models.prescription import (
    Prescription,
    Patient,
    PrescriptionDrug,
)
from models.segment import Exams
from models.enums import MemoryEnum, FeatureEnum, DrugTypeEnum
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
    id_prescription: int,
):
    prescription, patient = _get_prescription_data(id_prescription=id_prescription)

    configs = _get_configs(prescription=prescription, patient=patient)
    interventions = _get_interventions(admission_number=prescription.admissionNumber)
    cn_data = _get_clinical_notes_stats(
        prescription=prescription, patient=patient, configs=configs
    )
    exam_data = _get_exams(patient=patient, prescription=prescription, configs=configs)
    drug_data = _get_drug_data(
        prescription=prescription,
        patient=patient,
        configs=configs,
        exam_data=exam_data,
        interventions=interventions,
    )

    p_data = {
        "idPrescription": str(prescription.id),
        "admissionNumber": prescription.admissionNumber,
        "date": prescription.date.isoformat(),
        "prescription": drug_data["source"][DrugTypeEnum.DRUG.value],
        "solution": drug_data["source"][DrugTypeEnum.SOLUTION.value],
        "procedures": drug_data["source"][DrugTypeEnum.PROCEDURE.value],
        "diet": drug_data["source"][DrugTypeEnum.DIET.value],
        "interventions": interventions,
        "alertExams": exam_data["alerts"],
        "clinicalNotes": cn_data["cn_count"],
        "complication": cn_data["cn_stats"].get("complication", 0),
        "clinicalNotesStats": cn_data["cn_stats"],
        "alertStats": drug_data["drug_list"].alertStats,
    }

    return prescriptionutils.getFeatures(
        result=p_data,
        agg_date=prescription.date if prescription.agg else None,
        intervals_for_agg_date=prescription.agg,
    )


@timed()
def _get_prescription_data(id_prescription: int) -> tuple[Prescription, Patient]:
    prescription_data = (
        db.session.query(Prescription, Patient)
        .outerjoin(Patient, Patient.admissionNumber == Prescription.admissionNumber)
        .filter(Prescription.id == id_prescription)
        .first()
    )
    if prescription_data is None:
        raise ValidationError(
            "Prescrição inexistente",
            "errors.invalidRecord",
            status.HTTP_400_BAD_REQUEST,
        )

    return prescription_data


@timed()
def _get_configs(prescription: Prescription, patient: Patient):
    data = {}

    # memory
    memory_itens = memory_service.get_by_kind(
        [MemoryEnum.MAP_SCHEDULES_FASTING.value, MemoryEnum.FEATURES.value]
    )
    data["schedules_fasting"] = memory_itens.get(
        MemoryEnum.MAP_SCHEDULES_FASTING.value, []
    )
    data["is_pmc"] = FeatureEnum.PRIMARY_CARE.value in memory_itens.get(
        MemoryEnum.FEATURES.value, []
    )

    data["is_cpoe"] = feature_service.is_cpoe()

    # patient data
    data["weight"] = patient.weight if patient.weight else None
    data["height"] = patient.height if patient.height else None
    data["age"] = dateutils.data2age(
        patient.birthdate.isoformat() if patient.birthdate else date.today().isoformat()
    )

    # features cache
    p_cache = (
        db.session.query(Prescription)
        .filter(
            Prescription.id
            == prescriptionutils.gen_agg_id(
                admission_number=prescription.admissionNumber,
                id_segment=prescription.idSegment,
                pdate=datetime.today(),
            )
        )
        .first()
    )
    if p_cache != None and p_cache.features != None:
        data["features_cache"] = p_cache.features
    else:
        data["features_cache"] = {}

    return data


@timed()
def _get_interventions(admission_number: int):
    return intervention_service.get_interventions(admissionNumber=admission_number)


@timed()
def _get_exams(patient: Patient, prescription: Prescription, configs: dict):
    exams = Exams.findLatestByAdmission(patient, prescription.idSegment, prevEx=False)

    examsJson = []
    alertExams = 0
    for e in exams:
        examsJson.append({"key": e, "value": exams[e]})
        alertExams += int(exams[e]["alert"])

    exams = dict(
        exams,
        **{
            "age": configs["age"],
            "weight": configs["weight"],
            "height": configs["height"],
        },
    )

    return {"exams": exams, "alerts": alertExams}


@timed()
def _get_drug_data(
    prescription: Prescription,
    patient: Patient,
    configs: dict,
    exam_data: dict,
    interventions,
):
    drugs = PrescriptionDrug.findByPrescription(
        idPrescription=prescription.id,
        admissionNumber=patient.admissionNumber,
        aggDate=prescription.date if prescription.agg else None,
        idSegment=prescription.idSegment,
        is_cpoe=configs.get("is_cpoe"),
        is_pmc=configs.get("is_pmc"),
    )

    relations = alert_interaction_service.find_relations(
        drug_list=drugs, is_cpoe=configs["is_cpoe"], id_patient=patient.idPatient
    )

    alerts = alert_service.find_alerts(
        drug_list=drugs,
        exams=exam_data["exams"],
        dialisys=patient.dialysis,
        pregnant=patient.pregnant,
        lactating=patient.lactating,
        schedules_fasting=configs["schedules_fasting"],
    )

    drug_list = DrugList(
        drugList=drugs,
        interventions=interventions,
        relations=relations,
        exams=exam_data["exams"],
        agg=prescription.agg,
        dialysis=patient.dialysis,
        alerts=alerts,
        is_cpoe=configs["is_cpoe"],
    )

    drug_list.sumAlerts()

    return {
        "relations": relations,
        "alerts": alerts,
        "drug_list": drug_list,
        "source": {
            DrugTypeEnum.DRUG.value: drug_list.getDrugType(
                [], [DrugTypeEnum.DRUG.value]
            ),
            DrugTypeEnum.SOLUTION.value: drug_list.getDrugType(
                [], [DrugTypeEnum.SOLUTION.value]
            ),
            DrugTypeEnum.PROCEDURE.value: drug_list.getDrugType(
                [], [DrugTypeEnum.PROCEDURE.value]
            ),
            DrugTypeEnum.DIET.value: drug_list.getDrugType(
                [], [DrugTypeEnum.DIET.value]
            ),
        },
    }


@timed()
def _get_clinical_notes_stats(
    prescription: Prescription, patient: Patient, configs: dict
):
    if configs["features_cache"].get("clinicalNotesStats", None) != None:
        cn_stats = configs["features_cache"].get("clinicalNotesStats")
    else:
        cn_stats = clinical_notes_service.get_admission_stats(
            admission_number=prescription.admissionNumber,
        )

    if configs["features_cache"].get("clinicalNotes", 0) != 0:
        cn_count = configs["features_cache"].get("clinicalNotes", 0)
    else:
        cn_count = clinical_notes_service.get_count(
            admission_number=prescription.admissionNumber,
            admission_date=patient.admissionDate,
        )

    return {"cn_stats": cn_stats, "cn_count": cn_count}
