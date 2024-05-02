from sqlalchemy.sql import distinct
from sqlalchemy import func, and_, text
from flask import escape as escape_html

from models.main import *
from models.appendix import *
from models.segment import *
from models.enums import IntegrationStatusEnum
from services import permission_service, drug_service as main_drug_service
from services.admin import (
    drug_service as admin_drug_service,
    integration_status_service,
    ai_service,
)
from exception.validation_error import ValidationError


def get_conversion_list(id_segment, user, show_prediction=False):
    if not permission_service.has_maintainer_permission(user):
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    active_drugs = db.session.query(distinct(Outlier.idDrug).label("idDrug")).cte(
        "active_drugs"
    )

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

    conversion_list = (
        db.session.query(
            func.count().over(),
            Drug.id,
            Drug.name,
            units.c.idMeasureUnit,
            MeasureUnitConvert.factor,
            MeasureUnit.description,
        )
        .join(active_drugs, Drug.id == active_drugs.c.idDrug)
        .join(units, Drug.id == units.c.idDrug)
        .outerjoin(
            MeasureUnitConvert,
            and_(
                MeasureUnitConvert.idDrug == Drug.id,
                MeasureUnitConvert.idSegment == id_segment,
                MeasureUnitConvert.idMeasureUnit == units.c.idMeasureUnit,
            ),
        )
        .outerjoin(MeasureUnit, MeasureUnit.id == units.c.idMeasureUnit)
        .order_by(Drug.name, MeasureUnitConvert.factor)
        .all()
    )

    result = []
    for i in conversion_list:
        result.append(
            {
                "idDrug": i[1],
                "name": i[2],
                "idMeasureUnit": i[3],
                "factor": i[4],
                "idSegment": escape_html(id_segment),
                "measureUnit": i[5],
            }
        )

    if show_prediction:
        return ai_service.get_factors(result)

    return result


def save_conversions(
    id_drug, id_segment, id_measure_unit_default, conversion_list, user
):
    if not permission_service.has_maintainer_permission(user):
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    overwrite = False
    if (
        integration_status_service.get_integration_status(user.schema)
        != IntegrationStatusEnum.PRODUCTION.value
    ):
        overwrite = True

    if (
        id_drug == None
        or id_segment == None
        or id_measure_unit_default == None
        or conversion_list == None
        or len(conversion_list) == 0
    ):
        raise ValidationError(
            "Parâmetros inválidos",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )

    for uc in conversion_list:
        if uc["factor"] == None or uc["factor"] == 0:
            raise ValidationError(
                "Fator de conversão inválido",
                "errors.invalidParams",
                status.HTTP_400_BAD_REQUEST,
            )

    da = (
        db.session.query(DrugAttributes)
        .filter(DrugAttributes.idDrug == id_drug)
        .filter(DrugAttributes.idSegment == id_segment)
        .first()
    )
    if da == None:
        da = main_drug_service.create_attributes_from_reference(
            id_drug=id_drug, id_segment=id_segment, user=user
        )
    else:
        if not overwrite and da.idMeasureUnit != id_measure_unit_default:
            raise ValidationError(
                "A alteração de Unidade Padrão deve ser executada através do Assistente para Geração de Escores.",
                "errors.businessRule",
                status.HTTP_400_BAD_REQUEST,
            )

    da.idMeasureUnit = id_measure_unit_default
    da.update = datetime.today()
    da.user = user.id

    db.session.flush()

    # set conversions
    _update_conversion_list(
        conversion_list=conversion_list,
        id_drug=id_drug,
        id_segment=id_segment,
        user=user,
    )

    # update other segments
    rejected_segments = []
    updated_segments = []
    segments = db.session.query(Segment).all()

    for s in segments:
        if s.id == id_segment:
            updated_segments.append(s.description)
            continue

        # set drug attributes
        da = (
            db.session.query(DrugAttributes)
            .filter(DrugAttributes.idDrug == id_drug)
            .filter(DrugAttributes.idSegment == s.id)
            .first()
        )
        if (
            not overwrite
            and da != None
            and da.idMeasureUnit != None
            and da.idMeasureUnit != id_measure_unit_default
        ):
            # do not update
            rejected_segments.append(s.description)
            continue
        else:
            updated_segments.append(s.description)

        if da == None:
            da = main_drug_service.create_attributes_from_reference(
                id_drug=id_drug, id_segment=s.id, user=user
            )

        da.idMeasureUnit = id_measure_unit_default
        da.update = datetime.today()
        da.user = user.id

        db.session.flush()

        # update conversions
        _update_conversion_list(
            conversion_list=conversion_list, id_drug=id_drug, id_segment=s.id, user=user
        )

    return {"updated": updated_segments, "rejected": rejected_segments}


def _update_conversion_list(conversion_list, id_drug, id_segment, user):
    for uc in conversion_list:
        insert_units = text(
            f"""
            insert into {user.schema}.unidadeconverte
                (idsegmento, fkmedicamento, fkunidademedida, fator)
            values 
                (:id_segment, :id_drug, :id_measure_unit, :factor)
            on conflict (idsegmento, fkmedicamento, fkunidademedida)
            do update set fator = :factor
        """
        )

        db.session.execute(
            insert_units,
            {
                "id_segment": id_segment,
                "id_drug": id_drug,
                "id_measure_unit": uc["idMeasureUnit"],
                "factor": uc["factor"],
            },
        )


def add_default_units(user):
    if not permission_service.has_maintainer_permission(user):
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )
    schema = user.schema

    admin_drug_service.fix_inconsistency(user)

    query = f"""
        with unidades as (
            select
                fkmedicamento, min(fkunidademedida) as fkunidademedida
            from ( 
                select 
                    fkmedicamento, fkunidademedida  
                from {schema}.prescricaoagg p 
                where 
                    p.fkunidademedida is not null 
                    and p.fkunidademedida <> ''
                    and p.fkmedicamento in (
                        select fkmedicamento from {schema}.medatributos m where m.fkunidademedida is null
                    )
                group by fkmedicamento, fkunidademedida
            ) a
            group by fkmedicamento 
            having count(*) = 1
        ), unidades_segmento as (
            select fkmedicamento, fkunidademedida, s.idsegmento  from unidades, {schema}.segmento s
        )
        update 
            {schema}.medatributos ma
        set 
            fkunidademedida = unidades_segmento.fkunidademedida
        from 
            unidades_segmento
        where 
            ma.fkmedicamento = unidades_segmento.fkmedicamento
            and ma.idsegmento = unidades_segmento.idsegmento
            and ma.fkunidademedida is null
    """

    insert_units = text(
        f"""
        insert into {schema}.unidadeconverte
            (idsegmento, fkmedicamento, fkunidademedida, fator)
        select 
            m.idsegmento, m.fkmedicamento, m.fkunidademedida, 1
        from 
            {schema}.medatributos m 
        where 
            m.fkunidademedida is not null 
            and m.fkunidademedida != ''
        on conflict (idsegmento, fkmedicamento, fkunidademedida)
        do nothing
    """
    )

    result = db.session.execute(query)

    db.session.execute(insert_units)

    return result


def copy_unit_conversion(id_segment_origin, id_segment_destiny, user):
    if not permission_service.has_maintainer_permission(user):
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )
    schema = user.schema

    if id_segment_origin == None or id_segment_destiny == None:
        raise ValidationError(
            "Segmento Inválido", "errors.invalidRecord", status.HTTP_400_BAD_REQUEST
        )

    if id_segment_origin == id_segment_destiny:
        raise ValidationError(
            "Segmento origem deve ser diferente do segmento destino",
            "errors.invalidRecord",
            status.HTTP_400_BAD_REQUEST,
        )

    query = text(
        f"""
        with conversao_origem as (
            select 
                ma.fkmedicamento, ma.idsegmento, ma.fkunidademedida
            from
                {schema}.medatributos ma
                inner join {schema}.medatributos madestino on (
                    ma.fkmedicamento = madestino.fkmedicamento
                    and madestino.idsegmento  = :idSegmentDestiny
                    and ma.fkunidademedida = madestino.fkunidademedida 
                )
            where 
                ma.idsegmento = :idSegmentOrigin
        )
        insert into {schema}.unidadeconverte (idsegmento, fkunidademedida, fator, fkmedicamento) (
            select 
                :idSegmentDestiny as idsegmento,
                u.fkunidademedida,
                u.fator,
                u.fkmedicamento
            from
                {schema}.unidadeconverte u
                inner join conversao_origem on (
                    u.fkmedicamento = conversao_origem.fkmedicamento 
                    and u.idsegmento = conversao_origem.idsegmento
                )
        )
        on conflict (fkunidademedida, idsegmento, fkmedicamento)
        do update set fator = excluded.fator
    """
    )

    return db.session.execute(
        query,
        {"idSegmentOrigin": id_segment_origin, "idSegmentDestiny": id_segment_destiny},
    )
