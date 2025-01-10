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
