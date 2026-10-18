"""Repository: drug attributes related operations"""

from sqlalchemy import text

from models.main import db


def copy_segment_drug_attributes(
    id_segment_origin: int, id_segment_destiny: int, schema: str, id_user: int
):
    """
    Copy all medatributos from one segment to another
    """

    query = text(
        f"""
        insert into {schema}.medatributos (
            fkmedicamento,
            idsegmento,
            antimicro,
            mav,
            controlados,
            naopadronizado,
            dosemaxima,
            renal,
            hepatico,
            plaquetas,
            idoso,
            sonda,
            divisor,
            usapeso,
            concentracao,
            concentracaounidade,
            linhabranca,
            fkunidademedida,
            custo,
            tempotratamento,
            quimio,
            fkunidademedidacusto,
            risco_queda,
            dialisavel,
            lactante,
            gestante,
            jejum,
            ref_dosemaxima,
            ref_dosemaxima_peso,
            update_at,
            update_by
        )
        select 
            fkmedicamento,
            :idSegmentDestiny,
            antimicro,
            mav,
            controlados,
            naopadronizado,
            dosemaxima,
            renal,
            hepatico,
            plaquetas,
            idoso,
            sonda,
            divisor,
            usapeso,
            concentracao,
            concentracaounidade,
            linhabranca,
            fkunidademedida,
            custo,
            tempotratamento,
            quimio,
            fkunidademedidacusto,
            risco_queda,
            dialisavel,
            lactante,
            gestante,
            jejum,
            ref_dosemaxima,
            ref_dosemaxima_peso,
            now(),
            :updateBy
        from 
            {schema}.medatributos
        where 
            idsegmento = :idSegmentOrigin
        ON CONFLICT (fkmedicamento, idsegmento) DO nothing
        """
    )

    return db.session.execute(
        query,
        {
            "idSegmentOrigin": id_segment_origin,
            "idSegmentDestiny": id_segment_destiny,
            "updateBy": id_user,
        },
    )
