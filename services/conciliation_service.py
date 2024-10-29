from datetime import datetime
from sqlalchemy import desc

from models.main import db, User
from models.prescription import Prescription, Patient, PrescriptionDrug
from models.enums import FeatureEnum, PatientConciliationStatusEnum
from utils import status, prescriptionutils
from services import (
    memory_service,
    prescription_agg_service,
    prescription_drug_edit_service,
)
from exception.validation_error import ValidationError
from decorators.has_permission_decorator import has_permission, Permission


@has_permission(Permission.WRITE_PRESCRIPTION)
def create_conciliation(admission_number: int, user_context: User):
    if not memory_service.has_feature(FeatureEnum.CONCILIATION_EDIT.value):
        raise ValidationError(
            "Feature desabilitada",
            "errors.unauthorizedFeature",
            status.HTTP_401_UNAUTHORIZED,
        )

    ref = prescription_agg_service.get_last_prescription(
        admission_number=admission_number
    )

    if ref == None:
        raise ValidationError(
            "Atendimento inválido", "errors.businessRules", status.HTTP_400_BAD_REQUEST
        )

    new_id = 90000000000000000 + prescriptionutils.gen_agg_id(
        admission_number=admission_number,
        id_segment=ref.idSegment,
        pdate=datetime.today().date(),
    )

    prescription = (
        db.session.query(Prescription).filter(Prescription.id == new_id).first()
    )

    if prescription != None:
        raise ValidationError(
            "Já existe uma conciliação para este atendimento no dia atual. Somente uma conciliação por dia é permitida.",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    prescription = Prescription()

    prescription.id = new_id
    prescription.date = datetime.today().date()
    prescription.expire = datetime.today().date()
    prescription.idDepartment = ref.idDepartment
    prescription.idHospital = ref.idHospital
    prescription.admissionNumber = ref.admissionNumber
    prescription.idPatient = ref.idPatient
    prescription.prescriber = user_context.name
    prescription.concilia = "s"
    prescription.agg = None
    prescription.update = datetime.today()
    prescription.user = user_context.id

    db.session.add(prescription)
    db.session.flush()

    patient = (
        db.session.query(Patient)
        .filter(Patient.admissionNumber == ref.admissionNumber)
        .first()
    )
    if (
        patient != None
        and patient.st_conciliation == PatientConciliationStatusEnum.PENDING.value
    ):
        patient.st_conciliation = PatientConciliationStatusEnum.CREATED.value
        db.session.flush()

    return prescription.id


@has_permission(Permission.READ_PRESCRIPTION)
def list_available(admission_number: int):
    if not memory_service.has_feature(FeatureEnum.CONCILIATION.value):
        raise ValidationError(
            "Feature desabilitada",
            "errors.unauthorizedFeature",
            status.HTTP_401_UNAUTHORIZED,
        )

    results = (
        db.session.query(Prescription)
        .filter(Prescription.admissionNumber == admission_number)
        .filter(Prescription.concilia != None)
        .order_by(desc(Prescription.date))
        .limit(5)
        .all()
    )

    c_list = []
    for p in results:
        c_list.append({"id": str(p.id), "date": p.date.isoformat(), "status": p.status})

    return c_list


@has_permission(Permission.WRITE_PRESCRIPTION)
def copy_conciliation(id_prescription: int, user_context: User):
    if not memory_service.has_feature(FeatureEnum.CONCILIATION_EDIT.value):
        raise ValidationError(
            "Feature desabilitada",
            "errors.unauthorizedFeature",
            status.HTTP_401_UNAUTHORIZED,
        )

    prescription = (
        db.session.query(Prescription)
        .filter(Prescription.id == id_prescription)
        .first()
    )

    if prescription == None:
        raise ValidationError(
            "Conciliação inexistente",
            "errors.invalidRecord",
            status.HTTP_400_BAD_REQUEST,
        )

    if prescription.concilia == None:
        raise ValidationError(
            "Conciliação inválida",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    admissions = (
        db.session.query(Patient)
        .filter(Patient.idPatient == prescription.idPatient)
        .order_by(desc(Patient.admissionDate))
        .limit(2)
        .all()
    )

    admission_list = [int(prescription.admissionNumber)]
    for a in admissions:
        admission_list.append(int(a.admissionNumber))

    from_conciliation = (
        db.session.query(Prescription)
        .filter(Prescription.id != id_prescription)
        .filter(Prescription.admissionNumber.in_(admission_list))
        .filter(Prescription.concilia != None)
        .filter(Prescription.date < prescription.date)
        .order_by(desc(Prescription.date))
        .first()
    )

    if from_conciliation == None:
        raise ValidationError(
            "Não foi encontrada conciliação anterior para este paciente",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    items = (
        db.session.query(PrescriptionDrug)
        .filter(PrescriptionDrug.idPrescription == from_conciliation.id)
        .filter(PrescriptionDrug.suspendedDate == None)
        .all()
    )

    for i in items:
        data = {
            "idPrescription": id_prescription,
            "source": i.source,
            "idDrug": i.idDrug,
            "dose": i.dose,
            "measureUnit": i.idMeasureUnit,
            "frequency": i.idFrequency,
            "interval": i.interval,
            "route": i.route,
            "recommendation": i.notes,
        }

        prescription_drug_edit_service.createPrescriptionDrug(
            data=data, user_context=user_context
        )
