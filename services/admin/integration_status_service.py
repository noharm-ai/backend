from sqlalchemy import func

from models.main import *
from models.appendix import *
from models.segment import *
from models.enums import MemoryEnum
from services import permission_service
from services.admin import memory_service as admin_memory_service
from exception.validation_error import ValidationError


def get_integration_status(schema):
    config = (
        db.session.query(SchemaConfig).filter(SchemaConfig.schemaName == schema).first()
    )

    if config == None:
        raise ValidationError(
            "Schema inválido",
            "errors.unauthorizedUser",
            status.HTTP_400_BAD_REQUEST,
        )

    return config.status


def get_status(user):
    if not permission_service.has_maintainer_permission(user):
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    return {
        "memory": _get_memory_status(),
        "segments": _get_segments(),
        "pendingFrequencies": _get_pending_frequencies(),
        "outliers": _get_outlier_status(),
        "pendingSubstances": _get_pending_substances(),
        "maxDose": _get_max_dose_count(),
        "interventionReason": _get_intervention_reasons_count(),
        "users": _get_users(user.schema),
        "exams": _get_exams_status(),
        "conversions": _get_conversion_status(),
    }


def _get_memory_status():
    return admin_memory_service.get_memory_itens(
        [
            MemoryEnum.GETNAME.value,
            MemoryEnum.FEATURES.value,
            MemoryEnum.MAP_IV.value,
            MemoryEnum.MAP_TUBE.value,
            MemoryEnum.MAP_ROUTES.value,
            MemoryEnum.MAP_ORIGIN_DRUG.value,
            MemoryEnum.MAP_ORIGIN_SOLUTION.value,
            MemoryEnum.MAP_ORIGIN_PROCEDURE.value,
            MemoryEnum.MAP_ORIGIN_DIET.value,
            MemoryEnum.MAP_ORIGIN_CUSTOM.value,
            MemoryEnum.REPORTS.value,
            MemoryEnum.REPORTS_INTERNAL.value,
        ]
    )


def _get_segments():
    status = (
        db.session.query(Segment.id, Segment.description, func.count())
        .outerjoin(SegmentDepartment, SegmentDepartment.id == Segment.id)
        .group_by(Segment.id, Segment.description)
    )

    result = []
    for s in status:
        result.append({"idSegment": s[0], "name": s[1], "departments": s[2]})

    return result


def _get_users(schema):
    query = (
        db.session.query(User).filter(User.active == True).filter(User.schema == schema)
    )
    active_count = query.count()
    active_cpoe = query.filter(func.cast(User.config, db.String).like("%cpoe%")).count()
    active_user_admin = query.filter(
        func.cast(User.config, db.String).like("%userAdmin%")
    ).count()

    return {
        "active": active_count,
        "activeCPOE": active_cpoe,
        "activeUserAdmin": active_user_admin,
    }


def _get_exams_status():
    status = (
        db.session.query(SegmentExam.idSegment, Segment.description, func.count())
        .join(Segment, Segment.id == SegmentExam.idSegment)
        .group_by(SegmentExam.idSegment, Segment.description)
        .all()
    )

    result = []
    for s in status:
        result.append(
            {
                "idSegment": s[0],
                "name": s[1],
                "count": s[2],
            }
        )

    return result


#     select se.idsegmento, count(*) as total from josemaria.segmentoexame  se
# inner join josemaria.segmento s on (se.idsegmento = s.idsegmento)
# group by se.idsegmento


def _get_pending_frequencies():
    return db.session.query(Frequency).filter(Frequency.dailyFrequency == None).count()


def _get_pending_substances():
    active_drugs = db.session.query(Outlier.idDrug).as_scalar()
    return (
        db.session.query(Drug)
        .filter(Drug.sctid == None)
        .filter(Drug.id.in_(active_drugs))
        .count()
    )


def _get_max_dose_count():
    return (
        db.session.query(DrugAttributes).filter(DrugAttributes.maxDose != None).count()
    )


def _get_intervention_reasons_count():
    return db.session.query(InterventionReason).count()


def _get_outlier_status():
    status = (
        db.session.query(
            Outlier.idSegment,
            Segment.description,
            func.count(),
            func.max(Outlier.update),
        )
        .join(Segment, Segment.id == Outlier.idSegment)
        .group_by(Outlier.idSegment, Segment.description)
    )

    result = []
    for s in status:
        result.append(
            {
                "idSegment": s[0],
                "name": s[1],
                "outliers": s[2],
                "lastUpdate": s[3].isoformat() if s[3] else None,
            }
        )

    return result


def _get_conversion_status():
    pending_conversions = (
        db.session.query(
            PrescriptionAgg.idSegment,
            PrescriptionAgg.idDrug,
            PrescriptionAgg.idMeasureUnit,
        )
        .outerjoin(
            MeasureUnitConvert,
            and_(
                MeasureUnitConvert.idSegment == PrescriptionAgg.idSegment,
                MeasureUnitConvert.idDrug == PrescriptionAgg.idDrug,
                MeasureUnitConvert.idMeasureUnit == PrescriptionAgg.idMeasureUnit,
            ),
        )
        .filter(PrescriptionAgg.idMeasureUnit != None)
        .filter(PrescriptionAgg.idMeasureUnit != "")
        .filter(MeasureUnitConvert.factor == None)
        .group_by(
            PrescriptionAgg.idSegment,
            PrescriptionAgg.idDrug,
            PrescriptionAgg.idMeasureUnit,
        )
        .subquery()
    )

    active_drugs = (
        db.session.query(Outlier.idDrug)
        .filter(Outlier.idSegment == DrugAttributes.idSegment)
        .as_scalar()
    )

    pending_price_conversions = (
        db.session.query(
            DrugAttributes.idSegment,
            DrugAttributes.idDrug,
            DrugAttributes.idMeasureUnitPrice,
        )
        .outerjoin(
            MeasureUnitConvert,
            and_(
                MeasureUnitConvert.idSegment == DrugAttributes.idSegment,
                MeasureUnitConvert.idDrug == DrugAttributes.idDrug,
                MeasureUnitConvert.idMeasureUnit == DrugAttributes.idMeasureUnitPrice,
            ),
        )
        .filter(DrugAttributes.idMeasureUnitPrice != None)
        .filter(DrugAttributes.idMeasureUnitPrice != "")
        .filter(MeasureUnitConvert.factor == None)
        .filter(DrugAttributes.idDrug.in_(active_drugs))
        .group_by(
            DrugAttributes.idSegment,
            DrugAttributes.idDrug,
            DrugAttributes.idMeasureUnitPrice,
        )
        .subquery()
    )

    return {
        "pendingConversions": db.session.query(pending_conversions).count(),
        "pendingPriceConversions": db.session.query(pending_price_conversions).count(),
    }
