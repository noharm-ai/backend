from sqlalchemy import desc, nullsfirst
from datetime import date
from utils import status

from models.main import db
from models.appendix import *
from models.prescription import *
from models.enums import (
    RoleEnum,
    PrescriptionAuditTypeEnum,
    DrugTypeEnum,
    FeatureEnum,
    PrescriptionReviewTypeEnum,
)
from exception.validation_error import ValidationError
from services import (
    prescription_drug_service,
    memory_service,
    permission_service,
    data_authorization_service,
)


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


def check_prescription(idPrescription, p_status, user, evaluation_time, alerts):
    roles = user.config["roles"] if user.config and "roles" in user.config else []
    if not permission_service.is_pharma(user):
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

    if not data_authorization_service.has_segment_authorization(
        id_segment=p.idSegment, user=user
    ):
        raise ValidationError(
            "Usuário não autorizado neste segmento",
            "errors.businessRules",
            status.HTTP_401_UNAUTHORIZED,
        )

    has_lock_feature = memory_service.has_feature(
        FeatureEnum.LOCK_CHECKED_PRESCRIPTION.value
    )

    if p_status == "0" and p.user != user.id:
        if has_lock_feature and RoleEnum.UNLOCK_CHECKED_PRESCRIPTION.value not in roles:
            raise ValidationError(
                "A checagem não pode ser desfeita, pois foi efetuada por outro usuário",
                "errors.businessError",
                status.HTTP_400_BAD_REQUEST,
            )

    extra_info = {
        "main_prescription": str(p.id),
        "main_is_agg": bool(p.agg),
        "main_evaluationStartDate": (
            p.features["evaluation"]["startDate"]
            if p.features != None
            and "evaluation" in p.features
            and "startDate" in p.features["evaluation"]
            else None
        ),
        "evaluationTime": evaluation_time or 0,
        "alerts": alerts,
    }

    results = []

    if p.agg:
        internals = _check_agg_internal_prescriptions(
            prescription=p,
            p_status=p_status,
            user=user,
            has_lock_feature=has_lock_feature,
            extra=extra_info,
        )
        single = _check_single_prescription(
            prescription=p,
            p_status=p_status,
            user=user,
            has_lock_feature=has_lock_feature,
            extra=extra_info,
        )

        for i in internals:
            results.append(i)
        if single:
            results.append(single)

    else:
        single = _check_single_prescription(
            prescription=p,
            p_status=p_status,
            user=user,
            has_lock_feature=has_lock_feature,
            extra=extra_info,
        )
        _update_agg_status(prescription=p, user=user, extra=extra_info)

        if single:
            results.append(single)

    return results


def _update_agg_status(prescription: Prescription, user: User, extra={}):
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
            prescription=agg_prescription, p_status=agg_status, user=user, extra=extra
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
    else:
        # discard all suspended
        active_count = (
            db.session.query(func.count().label("count"))
            .filter(PrescriptionDrug.idPrescription == Prescription.id)
            .filter(
                or_(
                    PrescriptionDrug.suspendedDate == None,
                    func.date(PrescriptionDrug.suspendedDate) >= agg_prescription.date,
                )
            )
            .as_scalar()
        )
        q = q.filter(active_count > 0)

    return q


def _check_agg_internal_prescriptions(
    prescription, p_status, user, has_lock_feature=False, extra={}
):
    q_internal_prescription = get_query_prescriptions_by_agg(
        agg_prescription=prescription, is_cpoe=user.cpoe()
    )
    q_internal_prescription = q_internal_prescription.filter(
        Prescription.status != p_status
    )

    prescriptions = q_internal_prescription.all()

    results = []

    for p in prescriptions:
        result = _check_single_prescription(
            prescription=p,
            p_status=p_status,
            user=user,
            parent_agg_date=prescription.date,
            has_lock_feature=has_lock_feature,
            extra=extra,
        )

        if result:
            results.append(result)

    return results


def _check_single_prescription(
    prescription, p_status, user, parent_agg_date=None, has_lock_feature=False, extra={}
):
    roles = user.config["roles"] if user.config and "roles" in user.config else []

    if p_status == "0" and prescription.user != user.id:
        if has_lock_feature and RoleEnum.UNLOCK_CHECKED_PRESCRIPTION.value not in roles:
            # skip this one
            return None

    prescription.status = p_status
    prescription.update = datetime.today()
    prescription.user = user.id

    audit_check(
        prescription=prescription,
        user=user,
        parent_agg_date=parent_agg_date,
        extra=extra,
    )

    db.session.flush()

    return {"idPrescription": str(prescription.id), "status": p_status}


def audit_check(prescription: Prescription, user: User, parent_agg_date=None, extra={}):
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
    a.extra = extra
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
    max_evaluation_minutes = 5

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


def review_prescription(idPrescription, user, review_type, evaluation_time):
    if not permission_service.is_pharma(user):
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    prescription = Prescription.query.get(idPrescription)
    if prescription is None:
        raise ValidationError(
            "Prescrição inexistente",
            "errors.invalidRegister",
            status.HTTP_400_BAD_REQUEST,
        )

    if not data_authorization_service.has_segment_authorization(
        id_segment=prescription.idSegment, user=user
    ):
        raise ValidationError(
            "Usuário não autorizado neste segmento",
            "errors.businessRules",
            status.HTTP_401_UNAUTHORIZED,
        )

    if not prescription.agg:
        raise ValidationError(
            "A revisão somente está disponível para Pacientes. Não é possível revisar prescrições individuais.",
            "errors.invalidRegister",
            status.HTTP_400_BAD_REQUEST,
        )

    if (
        review_type != PrescriptionReviewTypeEnum.REVIEWED.value
        and review_type != PrescriptionReviewTypeEnum.PENDING.value
    ):
        raise ValidationError(
            "Status de revisão inexistente",
            "errors.invalidRegister",
            status.HTTP_400_BAD_REQUEST,
        )

    prescription.reviewType = review_type
    db.session.flush()

    a = PrescriptionAudit()
    a.auditType = (
        PrescriptionAuditTypeEnum.REVISION.value
        if review_type == PrescriptionReviewTypeEnum.REVIEWED.value
        else PrescriptionAuditTypeEnum.UNDO_REVISION.value
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
    )

    a.extra = {
        "main_evaluationStartDate": (
            prescription.features["evaluation"]["startDate"]
            if prescription.features != None
            and "evaluation" in prescription.features
            and "startDate" in prescription.features["evaluation"]
            else None
        ),
        "evaluationTime": evaluation_time or 0,
    }

    a.agg = prescription.agg
    a.concilia = prescription.concilia
    a.bed = prescription.bed
    a.createdAt = datetime.today()
    a.createdBy = user.id

    db.session.add(a)

    db_user = db.session.query(User).filter(User.id == user.id).first()

    return {
        "reviewed": (
            True if review_type == PrescriptionReviewTypeEnum.REVIEWED.value else False
        ),
        "reviewedAt": datetime.today().isoformat(),
        "reviewedBy": db_user.name,
    }


def recalculate_prescription(id_prescription: int, user: User):
    p = Prescription.query.get(id_prescription)
    if p is None:
        raise ValidationError(
            "Prescrição inexistente.",
            "errors.invalidRegister",
            status.HTTP_400_BAD_REQUEST,
        )

    if p.agg:
        if user.cpoe():
            prescription_results = get_query_prescriptions_by_agg(
                agg_prescription=p, is_cpoe=user.cpoe(), only_id=True
            ).all()

            prescription_ids = []
            for item in prescription_results:
                prescription_ids.append(item.id)

            db.session.query(Prescription).filter(
                Prescription.id.in_(prescription_ids)
            ).filter(Prescription.idSegment == None).update(
                {
                    "idHospital": p.idHospital,
                    "idDepartment": p.idDepartment,
                    "idSegment": p.idSegment,
                },
                synchronize_session="fetch",
            )

            db.session.flush()

            query = text(
                f"""INSERT INTO {user.schema}.presmed
                    SELECT
                        pm.*
                    FROM
                        {user.schema}.presmed pm
                    WHERE 
                        fkprescricao = ANY(:prescriptionIds)
                """
            )

            db.session.execute(query, {"prescriptionIds": prescription_ids})
        else:
            query = text(
                "INSERT INTO "
                + user.schema
                + ".presmed \
                    SELECT pm.*\
                    FROM "
                + user.schema
                + ".presmed pm\
                    WHERE fkprescricao IN (\
                        SELECT fkprescricao\
                        FROM "
                + user.schema
                + ".prescricao p\
                        WHERE p.nratendimento = :admissionNumber"
                + "\
                        AND p.idsegmento IS NOT NULL \
                        AND (\
                            p.dtprescricao::date = "
                + "date(:prescDate) OR\
                            p.dtvigencia::date = "
                + "date(:prescDate)\
                        )\
                    );"
            )

            db.session.execute(
                query, {"admissionNumber": p.admissionNumber, "prescDate": p.date}
            )
    else:
        query = text(
            "INSERT INTO "
            + user.schema
            + ".presmed \
                    SELECT *\
                    FROM "
            + user.schema
            + ".presmed\
                    WHERE fkprescricao = :idPrescription"
            + ";"
        )

        db.session.execute(query, {"idPrescription": p.id})
