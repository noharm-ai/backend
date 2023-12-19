from sqlalchemy import desc, nullsfirst
from datetime import date
from flask_api import status

from models.main import db
from models.appendix import *
from models.prescription import *
from models.enums import RoleEnum, PrescriptionAuditTypeEnum, DrugTypeEnum, FeatureEnum
from exception.validation_error import ValidationError
from services import prescription_drug_service, memory_service


def search(search_key):
    q_presc_admission = (
        db.session.query(
            Prescription,
            Patient.birthdate.label("birthdate"),
            Patient.gender.label("gender"),
            Department.name.label("department"),
            Patient.admissionDate.label("admission_date"),
            func.row_number().over(order_by=desc(Prescription.date)).label("priority"),
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
    )

    q_concilia = (
        db.session.query(
            Prescription,
            Patient.birthdate.label("birthdate"),
            Patient.gender.label("gender"),
            Department.name.label("department"),
            Patient.admissionDate.label("admission_date"),
            func.row_number().over(order_by=desc(Prescription.date)).label("priority"),
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
            and_(
                Prescription.admissionNumber == search_key,
                Prescription.concilia != None,
            ),
        )
        .order_by(desc(Prescription.date))
        .limit(1)
    )

    return (
        q_presc_admission.union_all(q_concilia)
        .order_by("priority", nullsfirst(Prescription.concilia))
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
        agg_prescription=prescription, is_cpoe=user.cpoe()
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
            prescription=agg_prescription, p_status=agg_status, user=user
        )


def get_query_prescriptions_by_agg(
    agg_prescription: Prescription, is_cpoe=False, only_id=False
):
    is_pmc = memory_service.has_feature_nouser(FeatureEnum.PRIMARY_CARE.value)

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
        agg_prescription=prescription, is_cpoe=user.cpoe()
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

    _audit_check(prescription=prescription, user=user, parent_agg_date=parent_agg_date)

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

    return a.totalItens


def start_evaluation(id_prescription, user):
    roles = user.config["roles"] if user.config and "roles" in user.config else []
    if (
        RoleEnum.SUPPORT.value in roles
        or RoleEnum.ADMIN.value in roles
        or RoleEnum.READONLY.value in roles
        or RoleEnum.TRAINING.value in roles
    ):
        return

    p = Prescription.query.get(id_prescription)
    if p is None:
        raise ValidationError(
            "Prescrição inexistente",
            "errors.invalidRegister",
            status.HTTP_400_BAD_REQUEST,
        )

    if p.features == None:
        raise ValidationError(
            "Esta prescrição ainda não possui indicadores.",
            "errors.invalidRegister",
            status.HTTP_400_BAD_REQUEST,
        )

    if is_being_evaluated(p.features):
        return p.features["evaluation"] if "evaluation" in p.features else None
    else:
        current_user = db.session.query(User).filter(User.id == user.id).first()
        evaluation_object = {
            "userId": user.id,
            "userName": current_user.name,
            "startDate": datetime.today().isoformat(),
        }

        p.features = dict(p.features, **{"evaluation": evaluation_object})

        db.session.flush()

        return evaluation_object


def is_being_evaluated(features):
    max_evaluation_minutes = 10

    if (
        features != None
        and "evaluation" in features
        and "startDate" in features["evaluation"]
    ):
        evaluation_date = features["evaluation"]["startDate"]
        current_evaluation_minutes = (
            datetime.today() - datetime.fromisoformat(evaluation_date)
        ).total_seconds() / 60

        return current_evaluation_minutes <= max_evaluation_minutes

    return False
