from flask_api import status
from sqlalchemy import and_, or_, func

from models.main import *
from models.appendix import *
from models.segment import *
from models.enums import RoleEnum, DrugAdminSegment

from exception.validation_error import ValidationError


def get_drug_list(
    has_substance=None,
    has_price_conversion=None,
    has_default_unit=None,
    has_price_unit=None,
    has_inconsistency=None,
    has_missing_conversion=None,
    attribute_list=[],
    term=None,
    limit=10,
    offset=0,
    id_segment_list=None,
):
    SegmentOutlier = db.aliased(Segment)
    ConversionsAgg = db.aliased(MeasureUnitConvert)

    presc_query = (
        db.session.query(
            Outlier.idDrug.label("idDrug"), Outlier.idSegment.label("idSegment")
        )
        .group_by(Outlier.idDrug, Outlier.idSegment)
        .subquery()
    )

    conversions_query = (
        db.session.query(
            PrescriptionAgg.idDrug.label("idDrug"),
            PrescriptionAgg.idSegment.label("idSegment"),
        )
        .select_from(PrescriptionAgg)
        .outerjoin(
            ConversionsAgg,
            and_(
                ConversionsAgg.idSegment == PrescriptionAgg.idSegment,
                ConversionsAgg.idDrug == PrescriptionAgg.idDrug,
                ConversionsAgg.idMeasureUnit == PrescriptionAgg.idMeasureUnit,
            ),
        )
        .filter(PrescriptionAgg.idSegment != None)
        .filter(PrescriptionAgg.idMeasureUnit != None)
        .filter(ConversionsAgg.factor == None)
        .group_by(PrescriptionAgg.idDrug, PrescriptionAgg.idSegment)
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
            SegmentOutlier.description,
        )
        .select_from(presc_query)
        .join(Drug, presc_query.c.idDrug == Drug.id)
        .outerjoin(
            DrugAttributes,
            and_(
                DrugAttributes.idDrug == Drug.id,
                DrugAttributes.idSegment == presc_query.c.idSegment,
            ),
        )
        .outerjoin(Segment, Segment.id == DrugAttributes.idSegment)
        .outerjoin(
            MeasureUnitConvert,
            and_(
                MeasureUnitConvert.idSegment == Segment.id,
                MeasureUnitConvert.idDrug == Drug.id,
                MeasureUnitConvert.idMeasureUnit == DrugAttributes.idMeasureUnitPrice,
            ),
        )
        .outerjoin(Substance, Drug.sctid == Substance.id)
        .outerjoin(SegmentOutlier, SegmentOutlier.id == presc_query.c.idSegment)
    )

    if has_missing_conversion:
        q = q.outerjoin(
            conversions_query,
            and_(
                conversions_query.c.idDrug == presc_query.c.idDrug,
                conversions_query.c.idSegment == presc_query.c.idSegment,
            ),
        ).filter(conversions_query.c.idDrug != None)

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

    if has_price_unit != None:
        if has_price_unit:
            q = q.filter(DrugAttributes.idMeasureUnitPrice != None)
        else:
            q = q.filter(DrugAttributes.idMeasureUnitPrice == None)

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

    if has_inconsistency != None:
        if has_inconsistency:
            q = q.filter(DrugAttributes.idDrug == None)
        else:
            q = q.filter(DrugAttributes.idDrug != None)

    if len(attribute_list) > 0:
        bool_attributes = [
            ["mav", DrugAttributes.mav],
            ["idoso", DrugAttributes.elderly],
            ["controlados", DrugAttributes.controlled],
            ["antimicro", DrugAttributes.antimicro],
            ["quimio", DrugAttributes.chemo],
            ["sonda", DrugAttributes.tube],
            ["naopadronizado", DrugAttributes.notdefault],
            ["linhabranca", DrugAttributes.whiteList],
            ["renal", DrugAttributes.kidney],
            ["hepatico", DrugAttributes.liver],
            ["plaquetas", DrugAttributes.platelets],
            ["dosemaxima", DrugAttributes.maxDose],
        ]

        for a in bool_attributes:
            if a[0] in attribute_list:
                if str(a[1].type) == "BOOLEAN":
                    q = q.filter(a[1] == True)
                else:
                    q = q.filter(a[1] != None)

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

    fix_inconsistency(user)

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

    insert_units = f"""
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

    result = db.session.execute(query)

    db.session.execute(insert_units)

    return result


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


def fix_inconsistency(user):
    roles = user.config["roles"] if user.config and "roles" in user.config else []
    if RoleEnum.ADMIN.value not in roles and RoleEnum.TRAINING.value not in roles:
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )
    schema = user.schema

    query = f"""
        with inconsistentes as (
            select 
                distinct o.fkmedicamento, o.idsegmento 
            from 
                {schema}.outlier o 
                inner join {schema}.medicamento m on (o.fkmedicamento = m.fkmedicamento)
                left join {schema}.medatributos ma on (o.fkmedicamento = ma.fkmedicamento and o.idsegmento = ma.idsegmento)
            where 
                ma.fkmedicamento is null
        )
        insert into {schema}.medatributos (fkmedicamento, idsegmento)
        select fkmedicamento, idsegmento from inconsistentes
        on conflict 
        do nothing
    """

    return db.session.execute(query)


def copy_drug_attributes(
    id_segment_origin,
    id_segment_destiny,
    user,
    attributes,
    from_admin_schema=True,
    overwrite_all=False,
):
    roles = user.config["roles"] if user.config and "roles" in user.config else []
    if RoleEnum.ADMIN.value not in roles:
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    if (
        from_admin_schema
        and id_segment_origin != DrugAdminSegment.ADULT.value
        and id_segment_origin != DrugAdminSegment.KIDS.value
    ):
        raise ValidationError(
            "Segmento origem inválido",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )

    if not from_admin_schema and id_segment_origin == id_segment_destiny:
        raise ValidationError(
            "Segmento origem igual ao segmento destino",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )

    origin_schema = "hsc_test" if from_admin_schema else user.schema
    schema = user.schema

    only_support_filter = """
        and (
            ma.update_by = 0
            or ma.update_by is null
            or u.config::text like :supportRole
        )
    """

    base_attributes = [
        "renal",
        "hepatico",
        "plaquetas",
        "mav",
        "idoso",
        "controlados",
        "antimicro",
        "quimio",
        "sonda",
        "naopadronizado",
        "linhabranca",
        "dosemaxima",
    ]
    set_attributes = []
    for a in attributes:
        if a in base_attributes:
            set_attributes.append(f"{a} = destino.{a},")

    query = f"""
        with modelo as (
            select
                m.sctid,
                ma.renal,
                ma.hepatico,
                ma.plaquetas,
                ma.dosemaxima,
                coalesce(ma.mav, false) as mav,
                coalesce(ma.idoso, false) as idoso,
                coalesce(ma.controlados, false) as controlados,
                coalesce(ma.antimicro, false) as antimicro,
                coalesce(ma.quimio, false) as quimio,
                coalesce(ma.sonda, false) as sonda,
                coalesce(ma.naopadronizado, false) as naopadronizado,
                coalesce(ma.linhabranca, false) as linhabranca
            from
                {origin_schema}.medatributos ma
                inner join {origin_schema}.medicamento m on (ma.fkmedicamento = m.fkmedicamento)
                inner join public.substancia s on (m.sctid = s.sctid)
            where 
                ma.idsegmento = :idSegmentOrigin
        ),
        destino as (
            select 
                ma.fkmedicamento, ma.idsegmento, mo.*
            from
                {schema}.medatributos ma
                inner join {schema}.medicamento m on (ma.fkmedicamento = m.fkmedicamento)
                inner join public.substancia s on (m.sctid = s.sctid)
                inner join modelo mo on (s.sctid = mo.sctid)
                left join public.usuario u on (ma.update_by = u.idusuario)
            where 
                ma.idsegmento = :idSegmentDestiny
                {only_support_filter if not overwrite_all else ''}
        )
        update 
            {schema}.medatributos origem
        set 
            {''.join(set_attributes)}
            update_at = now(),
            update_by = :idUser
        from 
            destino
        where 
            origem.fkmedicamento = destino.fkmedicamento
            and origem.idsegmento = destino.idsegmento
    """

    return db.session.execute(
        query,
        {
            "idSegmentOrigin": id_segment_origin,
            "idSegmentDestiny": id_segment_destiny,
            "supportRole": f"%{RoleEnum.SUPPORT.value}%",
            "idUser": user.id,
        },
    )
