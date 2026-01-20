"""Service: admin global exam operations"""

from datetime import datetime

from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from models.appendix import GlobalExam
from models.main import User, db
from models.requests.admin.admin_global_exam import (
    GlobalExamListRequest,
    GlobalExamUpsertRequest,
)
from repository.admin import admin_global_exam_repository
from utils import dateutils, status


@has_permission(Permission.ADMIN_EXAMS)
def list_global_exams(request_data: GlobalExamListRequest, user_context: User):
    """List global exams"""
    results = admin_global_exam_repository.list_global_exams(request_data=request_data)

    exams = []
    for item in results:
        exams.append(
            {
                "tpExam": item.tp_exam,
                "name": item.name,
                "initials": item.initials,
                "measureunit": item.measureunit,
                "active": item.active,
                "minAdult": item.min_adult,
                "maxAdult": item.max_adult,
                "refAdult": item.ref_adult,
                "minPediatric": item.min_pediatric,
                "maxPediatric": item.max_pediatric,
                "refPediatric": item.ref_pediatric,
                "createdAt": dateutils.to_iso(item.created_at),
                "updatedAt": dateutils.to_iso(item.updated_at),
            }
        )

    return exams


@has_permission(Permission.ADMIN_EXAMS)
def upsert_global_exam(request_data: GlobalExamUpsertRequest, user_context: User):
    """Upsert global exam records"""

    if not request_data.tp_exam or not request_data.tp_exam.strip():
        raise ValidationError(
            "TP EXAME é obrigatório",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    exam = admin_global_exam_repository.get_global_exam_by_id(
        tp_exam=request_data.tp_exam
    )

    if exam:
        exam.updated_at = datetime.today()
        exam.updated_by = user_context.id
    else:
        exam = GlobalExam()
        exam.tp_exam = request_data.tp_exam
        exam.created_at = datetime.today()
        exam.created_by = user_context.id
        db.session.add(exam)

    # Validate required fields
    if not request_data.name or not request_data.name.strip():
        raise ValidationError(
            "Nome do exame é obrigatório",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    if not request_data.initials or not request_data.initials.strip():
        raise ValidationError(
            "Abreviação do exame é obrigatória",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    if not request_data.measureunit or not request_data.measureunit.strip():
        raise ValidationError(
            "Unidade de medida é obrigatória",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    # Validate numeric ranges
    if request_data.min_adult > request_data.max_adult:
        raise ValidationError(
            "Valor mínimo adulto deve ser menor que o valor máximo adulto",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    if request_data.min_pediatric > request_data.max_pediatric:
        raise ValidationError(
            "Valor mínimo pediátrico deve ser menor que o valor máximo pediátrico",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    exam.name = request_data.name
    exam.initials = request_data.initials
    exam.measureunit = request_data.measureunit
    exam.active = request_data.active
    exam.min_adult = request_data.min_adult
    exam.max_adult = request_data.max_adult
    exam.ref_adult = request_data.ref_adult
    exam.min_pediatric = request_data.min_pediatric
    exam.max_pediatric = request_data.max_pediatric
    exam.ref_pediatric = request_data.ref_pediatric

    db.session.flush()

    return exam.tp_exam
