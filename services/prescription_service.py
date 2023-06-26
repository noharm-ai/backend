from sqlalchemy import desc
from datetime import date

from models.main import db
from models.appendix import *
from models.prescription import *
from models.enums import RoleEnum, PrescriptionAuditTypeEnum, DrugTypeEnum, FeatureEnum
from exception.validation_error import ValidationError
from services import prescription_drug_service, memory_service


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

    if p.agg:
        agg_total_itens = _check_agg_internal_prescriptions(
            prescription=p, status=status, user=user
        )

        _check_single_prescription(
            prescription=p, status=status, user=user, agg_total_itens=agg_total_itens
        )
    else:
        _check_single_prescription(prescription=p, status=status, user=user)


def _check_agg_internal_prescriptions(prescription, status, user):
    total_itens = 0
    is_cpoe = user.cpoe()
    is_pmc = memory_service.has_feature(FeatureEnum.PRIMARY_CARE.value)

    q = (
        db.session.query(Prescription)
        .filter(Prescription.admissionNumber == prescription.admissionNumber)
        .filter(Prescription.status != status)
        .filter(Prescription.idSegment == prescription.idSegment)
        .filter(Prescription.concilia == None)
        .filter(Prescription.agg == None)
    )

    q = get_period_filter(q, Prescription, prescription.date, is_pmc, is_cpoe)

    prescriptions = q.all()

    for p in prescriptions:
        total_itens += _check_single_prescription(
            prescription=p, status=status, user=user
        )

    return total_itens


def _check_single_prescription(prescription, status, user, agg_total_itens=0):
    total_itens = 0
    prescription.status = status
    prescription.update = datetime.today()
    prescription.user = user.id

    if memory_service.has_feature(FeatureEnum.AUDIT.value):
        total_itens = _audit_check(
            prescription=prescription, userId=user.id, agg_total_itens=agg_total_itens
        )

    db.session.flush()

    return total_itens


def _audit_check(prescription: Prescription, userId: int, agg_total_itens=0):
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

    if prescription.agg:
        a.totalItens = agg_total_itens
    else:
        a.totalItens = prescription_drug_service.count_drugs_by_prescription(
            prescription.id,
            [
                DrugTypeEnum.DRUG.value,
                DrugTypeEnum.PROCEDURE.value,
                DrugTypeEnum.SOLUTION.value,
            ],
        )

    a.agg = prescription.agg
    a.concilia = prescription.concilia
    a.bed = prescription.bed
    a.createdAt = datetime.today()
    a.createdBy = userId

    db.session.add(a)

    return a.totalItens
