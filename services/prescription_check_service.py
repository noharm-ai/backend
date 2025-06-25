"""Service: Prescription Check related operations"""

from datetime import datetime, timedelta

from sqlalchemy import func, text

from decorators.has_permission_decorator import has_permission, Permission
from models.main import db, User
from models.prescription import (
    Prescription,
    PrescriptionAudit,
)
from models.enums import (
    FeatureEnum,
    PrescriptionAuditTypeEnum,
    DrugTypeEnum,
    PrescriptionReviewTypeEnum,
)
from repository import prescription_view_repository
from exception.validation_error import ValidationError
from utils import status
from services import (
    data_authorization_service,
    memory_service,
    prescription_drug_service,
    feature_service,
    user_service,
)
from security.role import Role


@has_permission(Permission.WRITE_PRESCRIPTION)
def check_prescription(
    idPrescription,
    p_status,
    user_context: User,
    user_permissions: list[Permission],
    evaluation_time,
    alerts,
    service_user=False,
    fast_check=False,
):
    """
    Check or uncheck a prescription.
    """

    p = db.session.query(Prescription).filter(Prescription.id == idPrescription).first()
    if p is None:
        raise ValidationError(
            "Prescrição inexistente",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    if p.status == p_status:
        raise ValidationError(
            (
                "Não houve alteração da situação: Prescrição já está checada"
                if p_status == "s"
                else "Não houve alteração da situação: A checagem já foi desfeita"
            ),
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    if not data_authorization_service.has_segment_authorization(
        id_segment=p.idSegment, user=user_context
    ):
        raise ValidationError(
            "Usuário não autorizado neste segmento",
            "errors.businessRules",
            status.HTTP_401_UNAUTHORIZED,
        )

    has_lock_feature = memory_service.has_feature(
        FeatureEnum.LOCK_CHECKED_PRESCRIPTION.value
    )

    if p_status == "0" and p.user != user_context.id:
        # TODO: refactor (when user has permission to override this?)
        if has_lock_feature:
            raise ValidationError(
                "A checagem não pode ser desfeita, pois foi efetuada por outro usuário",
                "errors.businessError",
                status.HTTP_400_BAD_REQUEST,
            )

    user_service.validate_return_integration(
        user_context=user_context, user_permissions=user_permissions
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
        "serviceUser": service_user,
        "fastCheck": fast_check,
    }

    results = []

    if p.agg:
        internals = _check_agg_internal_prescriptions(
            prescription=p,
            p_status=p_status,
            user=user_context,
            has_lock_feature=has_lock_feature,
            extra=extra_info,
        )
        single = _check_single_prescription(
            prescription=p,
            p_status=p_status,
            user=user_context,
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
            user=user_context,
            has_lock_feature=has_lock_feature,
            extra=extra_info,
        )
        _update_agg_status(prescription=p, user=user_context, extra=extra_info)

        if single:
            results.append(single)

    return results


def _update_agg_status(prescription: Prescription, user: User, extra={}):
    is_pmc = memory_service.has_feature_nouser(FeatureEnum.PRIMARY_CARE.value)
    unchecked_prescriptions = (
        prescription_view_repository.get_query_prescriptions_by_agg(
            agg_prescription=prescription,
            is_cpoe=feature_service.is_cpoe(),
            is_pmc=is_pmc,
            schema=user.schema,
        )
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


def _check_agg_internal_prescriptions(
    prescription, p_status, user, has_lock_feature=False, extra={}
):
    is_pmc = memory_service.has_feature_nouser(FeatureEnum.PRIMARY_CARE.value)
    q_internal_prescription = (
        prescription_view_repository.get_query_prescriptions_by_agg(
            agg_prescription=prescription,
            is_cpoe=feature_service.is_cpoe(),
            is_pmc=is_pmc,
            schema=user.schema,
        )
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
    if p_status == "0" and prescription.user != user.id:
        if has_lock_feature:
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

    _add_checkedindex(prescription=prescription, user=user)

    db.session.flush()

    return {"idPrescription": str(prescription.id), "status": p_status}


def _add_checkedindex(prescription: Prescription, user: User):
    if prescription.status != "s" or prescription.agg or prescription.concilia != None:
        return

    query = text(
        f"""
        INSERT INTO {user.schema}.checkedindex
        (
            nratendimento, fkmedicamento, doseconv, frequenciadia, sletapas, slhorafase,
            sltempoaplicacao, sldosagem, dtprescricao, via, horario, dose, complemento, fkprescricao, 
            created_at, created_by
        )
        SELECT 
            p.nratendimento,
            pm.fkmedicamento, 
            pm.doseconv, 
            pm.frequenciadia, 
            COALESCE(pm.sletapas, 0), 
            COALESCE(pm.slhorafase, 0), 
            COALESCE(pm.sltempoaplicacao, 0), 
            COALESCE(pm.sldosagem, 0),
            p.dtprescricao, 
            COALESCE(pm.via, ''), 
            COALESCE(left(pm.horario ,50), ''),
            pm.dose, 
            MD5(pm.complemento),
            p.fkprescricao,
            :createdAt,
            :idUser
        FROM 
            {user.schema}.prescricao p
            INNER JOIN {user.schema}.presmed pm ON pm.fkprescricao = p.fkprescricao 
        WHERE 
            p.fkprescricao = :idPrescription
            AND pm.dtsuspensao is null
    """
    )

    db.session.execute(
        query,
        {
            "createdAt": datetime.today(),
            "idUser": user.id,
            "idPrescription": prescription.id,
        },
    )

    # delete old records to force revalidation
    db.session.execute(
        text(f"""DELETE FROM {user.schema}.checkedindex WHERE created_at < :maxDate"""),
        {"maxDate": (datetime.today() - timedelta(days=15))},
    )


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


@has_permission(Permission.WRITE_PRESCRIPTION)
def review_prescription(
    idPrescription, user_context: User, review_type, evaluation_time
):

    prescription = Prescription.query.get(idPrescription)
    prescription = (
        db.session.query(Prescription).filter(Prescription.id == idPrescription).first()
    )
    if prescription is None:
        raise ValidationError(
            "Prescrição inexistente",
            "errors.invalidRegister",
            status.HTTP_400_BAD_REQUEST,
        )

    if not data_authorization_service.has_segment_authorization(
        id_segment=prescription.idSegment, user=user_context
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
        user=user_context,
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
    a.createdBy = user_context.id

    db.session.add(a)

    db_user = db.session.query(User).filter(User.id == user_context.id).first()

    return {
        "reviewed": (
            True if review_type == PrescriptionReviewTypeEnum.REVIEWED.value else False
        ),
        "reviewedAt": datetime.today().isoformat(),
        "reviewedBy": db_user.name,
    }


@has_permission(Permission.RUN_AS)
def static_check(
    id_prescription: int,
    p_status: str,
    id_origin_user: int,
    user_context: User,
    user_permissions: list[Permission] = [],
):
    origin_user = (
        db.session.query(User)
        .filter(User.schema == user_context.schema)
        .filter(User.external == id_origin_user)
        .filter(User.active == True)
        .first()
    )

    if not origin_user:
        raise ValidationError(
            "Usuário origem inválido",
            "errors.invalidRegister",
            status.HTTP_400_BAD_REQUEST,
        )

    permissions = Role.get_permissions_from_user(origin_user)

    if Permission.WRITE_PRESCRIPTION not in permissions:
        raise ValidationError(
            "Usuário origem não possui permissão para checagem",
            "errors.invalidPermission",
            status.HTTP_400_BAD_REQUEST,
        )

    return check_prescription(
        idPrescription=id_prescription,
        p_status=p_status,
        user_context=origin_user,
        evaluation_time=0,
        alerts=[],
        service_user=True,
        user_permissions=user_permissions,
    )
