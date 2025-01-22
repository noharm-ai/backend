from sqlalchemy import text

from models.main import db


def update_dose_max(update_list: list[dict], schema: str):
    update_table = []

    for item in update_list:
        update_table.append(
            f"""({item.get("idDrug")}, {item.get("idSegment")}, {item.get("dosemax", "null")}, {item.get("dosemaxWeight", "null")})"""
        )

    query = text(
        f"""
        with update_table as (
            select * from (values {",".join(update_table)}) AS t (fkmedicamento, idsegmento, ref_dosemaxima, ref_dosemaxima_peso)
        )
        update
            {schema}.medatributos
        set 
            ref_dosemaxima = update_table.ref_dosemaxima::float,
            ref_dosemaxima_peso = update_table.ref_dosemaxima_peso::float
        from
            update_table
        where 
            update_table.fkmedicamento = {schema}.medatributos.fkmedicamento
            and update_table.idsegmento = {schema}.medatributos.idsegmento
        """
    )

    db.session.execute(query)


def copy_dose_max_from_ref(schema: str, update_by: int):
    """
    Updates dosemax attribute if its empty or updated by internal staff
    """

    query = text(
        f"""
        with update_table as (
            select 
                m.fkmedicamento, 
                m.idsegmento, 
                case 
                    when m.usapeso then m.ref_dosemaxima_peso
                    else m.ref_dosemaxima
                end as dosemaxima
            from 
                {schema}.medatributos m 
                left join public.usuario u on (m.update_by = u.idusuario)
            where 
                (
                    m.dosemaxima is null
                    or u."schema" = 'hsc_test'
                )
                and (
                    (m.usapeso = true and m.ref_dosemaxima_peso is not null)
                    or 
                    ((m.usapeso = false or m.usapeso is null) and m.ref_dosemaxima is not null)
                )
        )
        update
            {schema}.medatributos
        set 
            dosemaxima = update_table.dosemaxima::float,
            update_at = now(),
            update_by = :updateBy
        from
            update_table
        where 
            update_table.fkmedicamento = {schema}.medatributos.fkmedicamento
            and update_table.idsegmento = {schema}.medatributos.idsegmento
        """
    )

    return db.session.execute(query, {"updateBy": update_by})
