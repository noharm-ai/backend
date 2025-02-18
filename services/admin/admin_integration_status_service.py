from sqlalchemy import func, text, distinct, and_

from models.main import db, User, PrescriptionAgg, Outlier, Drug, DrugAttributes
from models.appendix import (
    SchemaConfig,
    Frequency,
    SegmentDepartment,
    InterventionReason,
    MeasureUnitConvert,
)
from models.segment import SegmentExam, Segment
from models.enums import MemoryEnum
from services.admin import admin_memory_service
from exception.validation_error import ValidationError
from decorators.has_permission_decorator import has_permission, Permission
from utils import status


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


@has_permission(Permission.INTEGRATION_STATUS)
def get_status(user_context: User):
    return {
        "status": get_integration_status(user_context.schema),
        "memory": _get_memory_status(),
        "segments": _get_segments(),
        "pendingFrequencies": _get_pending_frequencies(),
        "outliers": _get_outlier_status(),
        "pendingSubstances": _get_pending_substances(),
        "maxDose": _get_max_dose_count(),
        "interventionReason": _get_intervention_reasons_count(),
        "users": _get_users(user_context.schema),
        "exams": _get_exams_status(),
        "conversions": _get_conversion_status(),
        "tables": _get_table_stats(user_context.schema),
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
    active_drugs = db.session.query(
        distinct(Outlier.idDrug).label("idDrug"),
        Outlier.idSegment.label("idSegment"),
    ).cte("active_drugs")

    prescribed_units = (
        db.session.query(
            PrescriptionAgg.idDrug.label("idDrug"),
            PrescriptionAgg.idMeasureUnit.label("idMeasureUnit"),
        )
        .filter(PrescriptionAgg.idMeasureUnit != None)
        .filter(PrescriptionAgg.idMeasureUnit != "")
        .group_by(PrescriptionAgg.idDrug, PrescriptionAgg.idMeasureUnit)
    )

    current_units = (
        db.session.query(
            MeasureUnitConvert.idDrug.label("idDrug"),
            MeasureUnitConvert.idMeasureUnit.label("idMeasureUnit"),
        )
        .filter(MeasureUnitConvert.idMeasureUnit != None)
        .filter(MeasureUnitConvert.idMeasureUnit != "")
        .group_by(MeasureUnitConvert.idDrug, MeasureUnitConvert.idMeasureUnit)
    )

    price_units = (
        db.session.query(
            DrugAttributes.idDrug.label("idDrug"),
            DrugAttributes.idMeasureUnitPrice.label("idMeasureUnit"),
        )
        .filter(DrugAttributes.idMeasureUnitPrice != None)
        .filter(DrugAttributes.idMeasureUnitPrice != "")
        .group_by(DrugAttributes.idDrug, DrugAttributes.idMeasureUnitPrice)
    )

    units = prescribed_units.union(price_units, current_units).cte("units")

    count = (
        db.session.query(Drug)
        .join(active_drugs, Drug.id == active_drugs.c.idDrug)
        .join(units, Drug.id == units.c.idDrug)
        .outerjoin(
            MeasureUnitConvert,
            and_(
                MeasureUnitConvert.idDrug == Drug.id,
                MeasureUnitConvert.idSegment == active_drugs.c.idSegment,
                MeasureUnitConvert.idMeasureUnit == units.c.idMeasureUnit,
            ),
        )
        .filter(MeasureUnitConvert.factor == None)
        .count()
    )

    return {
        "pendingConversions": count,
    }


def _get_table_stats(schema):
    query = text(
        f"""
        select 
            n_live_tup as total_rows, relname
        from
            pg_stat_user_tables 
        where 
            schemaname = :schemaname
            and relname in ('alergia', 'cultura', 'evolucao', 'exame', 'frequencia', 'medicamento', 'pessoa', 'prescricao', 'prescricaoagg', 'presmed', 'setor', 'unidademedida')
        order by 
            relname
    """
    )

    results = db.session.execute(query, {"schemaname": schema})

    list = []
    for i in results:
        list.append({"table": i[1], "count": i[0]})

    return list
