from flask_api import status
from sqlalchemy import and_, or_, func

from models.main import *
from models.appendix import *
from models.segment import *
from models.enums import RoleEnum

from exception.validation_error import ValidationError


def get_drug_list(
    has_substance=None,
    has_price_conversion=None,
    has_default_unit=None,
    has_prescription=None,
    term=None,
    limit=10,
    offset=0,
    id_segment_list=None,
):
    presc_query = (
        db.session.query(
            Outlier.idDrug.label("idDrug"), Outlier.idSegment.label("idSegment")
        )
        .group_by(Outlier.idDrug, Outlier.idSegment)
        .subquery()
    )

    q = (
        db.session.query(
            Drug.id,
            Drug.name,
            Segment.id,
            Segment.description,
            DrugAttributes.idMeasureUnit,
            DrugAttributes.idMeasureUnitPrice,
            DrugAttributes.price,
            Drug.sctid,
            MeasureUnitConvert.factor,
            func.count().over(),
            Substance.name,
        )
        .select_from(Drug)
        .join(DrugAttributes, DrugAttributes.idDrug == Drug.id)
        .join(Segment, Segment.id == DrugAttributes.idSegment)
        .outerjoin(
            MeasureUnitConvert,
            and_(
                MeasureUnitConvert.idSegment == Segment.id,
                MeasureUnitConvert.idDrug == Drug.id,
                MeasureUnitConvert.idMeasureUnit == DrugAttributes.idMeasureUnitPrice,
            ),
        )
        .outerjoin(Substance, Drug.sctid == Substance.id)
        .outerjoin(
            presc_query,
            and_(
                presc_query.c.idDrug == Drug.id, presc_query.c.idSegment == Segment.id
            ),
        )
    )

    if has_substance != None:
        if has_substance:
            q = q.filter(Substance.id != None)
        else:
            q = q.filter(Substance.id == None)

    if has_default_unit != None:
        if has_default_unit:
            q = q.filter(DrugAttributes.idMeasureUnit != None)
        else:
            q = q.filter(DrugAttributes.idMeasureUnit == None)

    if has_price_conversion != None:
        if has_price_conversion:
            q = q.filter(
                or_(
                    MeasureUnitConvert.factor != None,
                    DrugAttributes.idMeasureUnitPrice == DrugAttributes.idMeasureUnit,
                )
            )
        else:
            q = q.filter(
                and_(
                    MeasureUnitConvert.factor == None,
                    func.coalesce(DrugAttributes.idMeasureUnitPrice, "")
                    != func.coalesce(DrugAttributes.idMeasureUnit, ""),
                    DrugAttributes.idMeasureUnitPrice != None,
                )
            )

    if has_prescription != None:
        if has_prescription:
            q = q.filter(presc_query.c.idDrug != None)
        else:
            q = q.filter(presc_query.c.idDrug == None)

    if term:
        q = q.filter(Drug.name.ilike(term))

    if id_segment_list and len(id_segment_list) > 0:
        q = q.filter(DrugAttributes.idSegment.in_(id_segment_list))

    return q.order_by(Drug.name, Segment.description).limit(limit).offset(offset).all()


def update_price_factor(id_drug, id_segment, factor, user):
    roles = user.config["roles"] if user.config and "roles" in user.config else []
    if RoleEnum.ADMIN.value not in roles and RoleEnum.TRAINING.value not in roles:
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    attributes = (
        db.session.query(DrugAttributes)
        .filter(DrugAttributes.idDrug == id_drug)
        .filter(DrugAttributes.idSegment == id_segment)
        .first()
    )

    if attributes == None:
        raise ValidationError(
            "Registro inexistente", "errors.invalidRecord", status.HTTP_400_BAD_REQUEST
        )

    if attributes.idMeasureUnitPrice == None:
        raise ValidationError(
            "Medicamento não possui unidade de custo definida",
            "errors.invalidRecord",
            status.HTTP_400_BAD_REQUEST,
        )

    conversion = MeasureUnitConvert.query.get(
        (attributes.idMeasureUnitPrice, id_drug, id_segment)
    )

    if conversion is None:
        conversion = MeasureUnitConvert()
        conversion.idMeasureUnit = attributes.idMeasureUnitPrice
        conversion.idDrug = id_drug
        conversion.idSegment = id_segment
        conversion.factor = factor

        db.session.add(conversion)
    else:
        conversion.factor = factor

        db.session.flush()


def update_substance(id_drug, sctid, user):
    roles = user.config["roles"] if user.config and "roles" in user.config else []
    if RoleEnum.ADMIN.value not in roles and RoleEnum.TRAINING.value not in roles:
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    drug = Drug.query.get(id_drug)

    if drug == None:
        raise ValidationError(
            "Registro inexistente", "errors.invalidRecord", status.HTTP_400_BAD_REQUEST
        )

    drug.sctid = sctid
    db.session.flush()


def add_default_units(user):
    roles = user.config["roles"] if user.config and "roles" in user.config else []
    if RoleEnum.ADMIN.value not in roles and RoleEnum.TRAINING.value not in roles:
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )
    schema = user.schema

    query = f"""
        with unidades as (
            select
                fkmedicamento,
                idsegmento,
                min(fkunidademedida) as fkunidademedida
            from (
                select 
                    pagg.fkmedicamento,
                    pagg.idsegmento,
                    pagg.fkunidademedida
                from
                    {schema}.prescricaoagg pagg
                where
                    pagg.fkmedicamento in (
                        select fkmedicamento from {schema}.medatributos m where m.fkunidademedida is null
                    )
                group by
                    pagg.fkmedicamento,
                    pagg.idsegmento,
                    pagg.fkunidademedida 
            ) a
            where 
                fkunidademedida is not null
            group by
                fkmedicamento,
                idsegmento
            having count(*) = 1
        )
        update 
            {schema}.medatributos ma
        set 
            fkunidademedida = unidades.fkunidademedida
        from 
            unidades
        where 
            ma.fkmedicamento = unidades.fkmedicamento
            and ma.idsegmento = unidades.idsegmento
            and ma.fkunidademedida is null
    """

    return db.session.execute(query)


def copy_unit_conversion(id_segment_origin, id_segment_destiny, user):
    roles = user.config["roles"] if user.config and "roles" in user.config else []
    if RoleEnum.ADMIN.value not in roles and RoleEnum.TRAINING.value not in roles:
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

    query = f"""
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

    return db.session.execute(
        query,
        {"idSegmentOrigin": id_segment_origin, "idSegmentDestiny": id_segment_destiny},
    )
