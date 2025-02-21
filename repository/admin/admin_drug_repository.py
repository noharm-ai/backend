"""Repository: drug related operations"""

from sqlalchemy import text

from models.main import db, User
from models.segment import Segment
from models.enums import DrugAttributesAuditTypeEnum, SegmentTypeEnum


def copy_attributes(
    from_admin_schema: bool,
    id_segment_origin: int,
    id_segment_destiny: int,
    attributes: list[str],
    user_context: User,
    overwrite_all: bool = False,
):
    """ "
    Copy attributes from substance or one segment to another
    """
    only_support_filter = """
        and (
            ma.update_by = 0
            or ma.update_by is null
            or u.schema = 'hsc_test'
        )
    """

    reference_query = _get_attributes_reference_query(
        from_admin_schema=from_admin_schema,
        id_segment_destiny=id_segment_destiny,
        schema=user_context.schema,
    )

    query = f"""
        with modelo as (
            {reference_query}
        ),
        destino as (
            select 
                ma.fkmedicamento, ma.idsegmento, mo.*
            from
                {user_context.schema}.medatributos ma
                inner join {user_context.schema}.medicamento m on (ma.fkmedicamento = m.fkmedicamento)
                inner join public.substancia s on (m.sctid = s.sctid)
                inner join modelo mo on (s.sctid = mo.sctid)
                left join public.usuario u on (ma.update_by = u.idusuario)
            where 
                ma.idsegmento = :idSegmentDestiny
                {only_support_filter if not overwrite_all else ''}
        )
    """

    audit_stmt = text(
        f"""
        {query}
        insert into 
            {user_context.schema}.medatributos_audit 
            (tp_audit, fkmedicamento, idsegmento, extra, created_at, created_by)
        select 
            {DrugAttributesAuditTypeEnum.COPY_FROM_REFERENCE.value}, d.fkmedicamento, d.idsegmento, :extra, now(), :idUser
        from
	        destino d
    """
    )

    db.session.execute(
        audit_stmt,
        {
            "idSegmentOrigin": id_segment_origin,
            "idSegmentDestiny": id_segment_destiny,
            "idUser": user_context.id,
            "extra": '{"attributes": "' + ",".join(attributes) + '"}',
        },
    )

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
        "risco_queda",
        "dialisavel",
        "lactante",
        "gestante",
        "jejum",
    ]
    if not from_admin_schema:
        base_attributes.append("fkunidademedidacusto")
        base_attributes.append("custo")

    set_attributes = []
    for a in attributes:
        if a in base_attributes:
            set_attributes.append(f"{a} = destino.{a},")

    update_stmt = text(
        f"""
        {query}
        update 
            {user_context.schema}.medatributos origem
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
    )

    print("update", update_stmt)

    return db.session.execute(
        update_stmt,
        {
            "idSegmentOrigin": id_segment_origin,
            "idSegmentDestiny": id_segment_destiny,
            "idUser": user_context.id,
        },
    )


def _get_attributes_reference_query(
    from_admin_schema: bool, id_segment_destiny: int, schema: str
):
    destiny_segment = (
        db.session.query(Segment).filter(Segment.id == id_segment_destiny).first()
    )

    if from_admin_schema:
        return f"""
            select
                s.sctid ,
                {"s.renal_pediatrico" if destiny_segment.type == SegmentTypeEnum.PEDIATRIC.value else "s.renal_adulto"} as renal,
                {"s.hepatico_pediatrico" if destiny_segment.type == SegmentTypeEnum.PEDIATRIC.value else "s.hepatico_adulto"} as hepatico,
                s.plaquetas,
                s.risco_queda,
                s.lactante,
                s.gestante,
                coalesce('antimicro' = any(s.tags), false) as antimicro,
                coalesce('surveillance' = any(s.tags), false) as mav,
                coalesce('controlled' = any(s.tags), false) as controlados,
                coalesce('pim' = any(s.tags), false) as idoso,
                coalesce('not_validated' = any(s.tags), false) as linhabranca,
                coalesce('tube' = any(s.tags), false) as sonda,
                coalesce('chemoterapy' = any(s.tags), false) as quimio,
                coalesce('dialyzable' = any(s.tags), false) as dialisavel,
                coalesce('fasting' = any(s.tags), false) as jejum
            from
                public.substancia s
        """

    return f"""
        select
            m.sctid,
            ma.renal,
            ma.hepatico,
            ma.plaquetas,
            ma.risco_queda,
            ma.lactante,
            ma.gestante,
            coalesce(ma.mav, false) as mav,
            coalesce(ma.idoso, false) as idoso,
            coalesce(ma.controlados, false) as controlados,
            coalesce(ma.antimicro, false) as antimicro,
            coalesce(ma.quimio, false) as quimio,
            coalesce(ma.sonda, false) as sonda,
            coalesce(ma.naopadronizado, false) as naopadronizado,
            coalesce(ma.linhabranca, false) as linhabranca,
            coalesce(ma.dialisavel, false) as dialisavel,
            coalesce(ma.jejum, false) as jejum,
            ma.fkunidademedidacusto,
            ma.custo
        from
            {schema}.medatributos ma
            inner join {schema}.medicamento m on (ma.fkmedicamento = m.fkmedicamento)
            inner join public.substancia s on (m.sctid = s.sctid)
        where 
            ma.idsegmento = :idSegmentOrigin
    """
