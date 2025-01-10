from sqlalchemy.sql import distinct
from sqlalchemy import func, and_, text
from markupsafe import escape as escape_html
from datetime import datetime

from models.main import db, User, PrescriptionAgg
from models.prescription import (
    Outlier,
    MeasureUnitConvert,
    DrugAttributes,
    Drug,
    MeasureUnit,
    Substance,
)
from models.segment import Segment
from models.enums import IntegrationStatusEnum, SegmentTypeEnum
from services import drug_service as main_drug_service
from services.admin import (
    admin_ai_service,
    admin_drug_service,
    admin_integration_status_service,
)
from decorators.has_permission_decorator import has_permission, Permission
from exception.validation_error import ValidationError
from utils import status
from models.requests.admin.admin_unit_conversion_request import SetFactorRequest


@has_permission(Permission.ADMIN_UNIT_CONVERSION)
def get_conversion_list(id_segment, show_prediction=False):
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

    substance_units = (
        db.session.query(
            DrugAttributes.idDrug.label("idDrug"),
            func.min(MeasureUnit.id).label("idMeasureUnit"),
        )
        .join(Drug, Drug.id == DrugAttributes.idDrug)
        .join(Substance, Substance.id == Drug.sctid)
        .join(MeasureUnit, Substance.default_measureunit == MeasureUnit.measureunit_nh)
        .filter(Substance.default_measureunit != None)
        .group_by(DrugAttributes.idDrug)
    )

    units = prescribed_units.union(price_units, current_units, substance_units).cte(
        "units"
    )

    conversion_list = (
        db.session.query(
            func.count().over(),
            Drug.id,
            Drug.name,
            units.c.idMeasureUnit,
            MeasureUnitConvert.factor,
            MeasureUnit.description,
            Drug.sctid,
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
        .outerjoin(Substance, Drug.sctid == Substance.id)
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
                "sctid": i.sctid,
            }
        )

    if show_prediction:
        return admin_ai_service.get_factors(result)

    return result


@has_permission(Permission.ADMIN_UNIT_CONVERSION)
def save_conversions(
    id_drug, id_segment, id_measure_unit_default, conversion_list, user_context: User
):

    overwrite = False
    if (
        admin_integration_status_service.get_integration_status(user_context.schema)
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
            id_drug=id_drug, id_segment=id_segment, user=user_context
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
    da.user = user_context.id

    db.session.flush()

    # set conversions
    _update_conversion_list(
        conversion_list=conversion_list,
        id_drug=id_drug,
        id_segment=id_segment,
        user=user_context,
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
                id_drug=id_drug, id_segment=s.id, user=user_context
            )

        da.idMeasureUnit = id_measure_unit_default
        da.update = datetime.today()
        da.user = user_context.id

        db.session.flush()

        # update conversions
        _update_conversion_list(
            conversion_list=conversion_list,
            id_drug=id_drug,
            id_segment=s.id,
            user=user_context,
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


@has_permission(Permission.ADMIN_UNIT_CONVERSION)
def add_default_units(user_context: User):
    schema = user_context.schema

    admin_drug_service.fix_inconsistency()

    query = text(
        f"""
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
    )

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


@has_permission(Permission.ADMIN_UNIT_CONVERSION)
def copy_unit_conversion(id_segment_origin, id_segment_destiny, user_context: User):
    schema = user_context.schema

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


@has_permission(Permission.ADMIN_DRUGS)
def sut_substanceunit_factor(request_data: SetFactorRequest):
    drug_info = (
        db.session.query(DrugAttributes, Drug, Substance, Segment, MeasureUnit)
        .join(Drug, DrugAttributes.idDrug == Drug.id)
        .join(Segment, DrugAttributes.idSegment == Segment.id)
        .join(Substance, Drug.sctid == Substance.id)
        .outerjoin(MeasureUnit, DrugAttributes.idMeasureUnit == MeasureUnit.id)
        .filter(DrugAttributes.idDrug == request_data.idDrug)
        .filter(DrugAttributes.idSegment == request_data.idSegment)
        .first()
    )

    if drug_info == None:
        raise ValidationError(
            "Registro inexistente", "errors.invalidRecord", status.HTTP_400_BAD_REQUEST
        )

    attributes: DrugAttributes = drug_info.DrugAttributes
    substance: Substance = drug_info.Substance
    default_measure_unit: MeasureUnit = drug_info.MeasureUnit
    segment: Segment = drug_info.Segment

    if not attributes.idMeasureUnit:
        raise ValidationError(
            "Medicamento não possui unidade padrão definida",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    if not substance.default_measureunit:
        raise ValidationError(
            "Substância não possui unidade padrão definida",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    if (
        default_measure_unit
        and default_measure_unit.measureunit_nh == substance.default_measureunit
    ):
        raise ValidationError(
            "A unidade de medida da substância é igual a do medicamento",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    measureunit = (
        db.session.query(MeasureUnit)
        .filter(MeasureUnit.measureunit_nh == substance.default_measureunit)
        .first()
    )

    if not measureunit:
        raise ValidationError(
            f"Não há relação para a unidade: {substance.default_measureunit}",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    conversion = (
        db.session.query(MeasureUnitConvert)
        .filter(
            MeasureUnitConvert.idDrug == request_data.idDrug,
            MeasureUnitConvert.idSegment == request_data.idSegment,
            MeasureUnitConvert.idMeasureUnit == measureunit.id,
        )
        .first()
    )

    factor = 1 / request_data.factor

    if conversion is None:
        conversion = MeasureUnitConvert()
        conversion.idMeasureUnit = measureunit.id
        conversion.idDrug = request_data.idDrug
        conversion.idSegment = request_data.idSegment
        conversion.factor = factor

        db.session.add(conversion)
    else:
        conversion.factor = factor
        db.session.flush()

    # update ref max dose
    subst_max_dose = None
    subst_max_dose_weight = None

    if segment.type == SegmentTypeEnum.ADULT.value:
        subst_max_dose = substance.maxdose_adult
        subst_max_dose_weight = substance.maxdose_adult_weight

    if segment.type == SegmentTypeEnum.PEDIATRIC.value:
        subst_max_dose = substance.maxdose_pediatric
        subst_max_dose_weight = substance.maxdose_pediatric_weight

    attributes.ref_maxdose = subst_max_dose * factor if subst_max_dose else None
    attributes.ref_maxdose_weight = (
        subst_max_dose_weight * factor if subst_max_dose_weight else None
    )
    db.session.flush()

    return {
        "idDrug": attributes.idDrug,
        "idSegment": attributes.idSegment,
        "refMaxDose": attributes.ref_maxdose,
        "refMaxDoseWeight": attributes.ref_maxdose_weight,
    }
