from sqlalchemy import desc
from datetime import date

from models.main import db
from models.appendix import *
from models.prescription import *
from models.enums import RoleEnum, PrescriptionAuditTypeEnum, DrugTypeEnum
from exception.validation_error import ValidationError
from services import prescription_drug_service


def search(search_key):
    return (
        db.session.query(
            Prescription,
            Patient.birthdate.label("birthdate"),
            Patient.gender.label("gender"),
            Department.name.label("department"),
        )
        .outerjoin(Patient, Patient.admissionNumber == Prescription.admissionNumber)
        .outerjoin(
            Department,
            and_(
                Department.id == Prescription.idDepartment,
                Department.idHospital == Prescription.idHospital,
            ),
        )
        .filter(
            or_(
                Prescription.id == search_key,
                and_(
                    Prescription.admissionNumber == search_key,
                    func.date(Prescription.date) <= date.today(),
                    Prescription.agg != None,
                ),
            )
        )
        .order_by(desc(Prescription.date))
        .limit(5)
        .all()
    )


def check_prescription(idPrescription, status, user):
    roles = user.config["roles"] if user.config and "roles" in user.config else []
    if RoleEnum.SUPPORT.value in roles:
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    p = Prescription.query.get(idPrescription)
    if p is None:
        raise ValidationError(
            "Prescrição inexistente",
            "errors.invalidRegister",
            status.HTTP_400_BAD_REQUEST,
        )

    p.status = status
    p.update = datetime.today()
    p.user = user.id

    _audit_check(p, user.id)


def _audit_check(prescription: Prescription, userId: int):
    a = PrescriptionAudit()
    a.auditType = (
        PrescriptionAuditTypeEnum.CHECK.value
        if prescription.status == "s"
        else PrescriptionAuditTypeEnum.UNCHECK.value
    )
    a.admissionNumber = prescription.admissionNumber
    a.idPrescription = prescription.id
    a.prescriptionDate = prescription.date
    a.idDepartment = prescription.idDepartment
    a.idSegment = prescription.idSegment
    a.totalItens = prescription_drug_service.count_drugs_by_prescription(
        prescription.id,
        [
            DrugTypeEnum.DRUG.value,
            DrugTypeEnum.PROCEDURE.value,
            DrugTypeEnum.SOLUTION.value,
        ],
    )
    a.agg = prescription.agg
    a.bed = prescription.bed
    a.createdAt = datetime.today()
    a.createdBy = userId

    db.session.add(a)
