from sqlalchemy import desc
from datetime import date
from flask_api import status

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


def check_prescription(idPrescription, p_status, user):
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
        _check_agg_internal_prescriptions(prescription=p, p_status=p_status, user=user)
        _check_single_prescription(prescription=p, p_status=p_status, user=user)

    else:
        _check_single_prescription(prescription=p, p_status=p_status, user=user)
        _update_agg_status(prescription=p, user=user)


def _update_agg_status(prescription: Prescription, user: User):
    unchecked_prescriptions = get_query_prescriptions_by_agg(
        agg_prescription=prescription, user=user
    )
    unchecked_prescriptions = unchecked_prescriptions.filter(Prescription.status != "s")

    agg_status = "0" if unchecked_prescriptions.count() > 0 else "s"

    agg_prescription = (
        db.session.query(Prescription)
        .filter(Prescription.admissionNumber == prescription.admissionNumber)
        .filter(Prescription.idSegment == prescription.idSegment)
        .filter(Prescription.agg != None)
        .filter(func.date(Prescription.date) == func.date(prescription.date))
        .first()
    )

    if agg_prescription is not None and agg_prescription.status != agg_status:
        _check_single_prescription(
            prescription=agg_prescription, status=agg_status, user=user
        )


def get_query_prescriptions_by_agg(agg_prescription: Prescription, user, only_id=False):
    is_cpoe = user.cpoe()
    is_pmc = memory_service.has_feature(FeatureEnum.PRIMARY_CARE.value)

    q = (
        db.session.query(Prescription.id if only_id else Prescription)
        .filter(Prescription.admissionNumber == agg_prescription.admissionNumber)
        .filter(Prescription.concilia == None)
        .filter(Prescription.agg == None)
    )

    q = get_period_filter(q, Prescription, agg_prescription.date, is_pmc, is_cpoe)

    if not is_cpoe:
        q = q.filter(Prescription.idSegment == agg_prescription.idSegment)

    return q


def _check_agg_internal_prescriptions(prescription, p_status, user):
    q_internal_prescription = get_query_prescriptions_by_agg(
        agg_prescription=prescription, user=user
    )
    q_internal_prescription = q_internal_prescription.filter(
        Prescription.status != p_status
    )

    prescriptions = q_internal_prescription.all()

    for p in prescriptions:
        _check_single_prescription(
            prescription=p,
            p_status=p_status,
            user=user,
            parent_agg_date=prescription.date,
        )


def _check_single_prescription(prescription, p_status, user, parent_agg_date=None):
    prescription.status = p_status
    prescription.update = datetime.today()
    prescription.user = user.id

    if memory_service.has_feature(FeatureEnum.AUDIT.value):
        _audit_check(
            prescription=prescription, user=user, parent_agg_date=parent_agg_date
        )

    db.session.flush()


def _audit_check(prescription: Prescription, user: User, parent_agg_date=None):
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
        prescription=prescription,
        drug_types=[
            DrugTypeEnum.DRUG.value,
            DrugTypeEnum.PROCEDURE.value,
            DrugTypeEnum.SOLUTION.value,
        ],
        user=user,
        parent_agg_date=parent_agg_date,
    )

    a.agg = prescription.agg
    a.concilia = prescription.concilia
    a.bed = prescription.bed
    a.createdAt = datetime.today()
    a.createdBy = user.id

    db.session.add(a)

    # print("///////check prescription////////", a.idPrescription, a.totalItens)

    return a.totalItens
