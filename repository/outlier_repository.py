"""Repository: outlier related operations"""

from sqlalchemy import text

from models.appendix import Notes
from models.main import Outlier, db


def list_drug_outliers(id_drug: int, id_segment: int) -> list[Outlier]:
    """List drug outliers"""
    return (
        db.session.query(Outlier, Notes)
        .outerjoin(Notes, Notes.idOutlier == Outlier.id)
        .filter(Outlier.idSegment == id_segment, Outlier.idDrug == id_drug)
        .order_by(Outlier.countNum.desc(), Outlier.frequency.asc())
        .all()
    )


def copy_segment_outliers(
    id_segment_origin: int, id_segment_destiny: int, schema: str, id_user: int
):
    """Copy all outlier records from one segment to another"""

    query = text(
        f"""
        insert into {schema}.outlier (
            fkmedicamento,
            idsegmento,
            contagem,
            doseconv,
            frequenciadia,
            escore,
            escoremanual,
            update_at,
            update_by
        )
        select
            fkmedicamento,
            :idSegmentDestiny,
            contagem,
            doseconv,
            frequenciadia,
            escore,
            escoremanual,
            now(),
            :updateBy
        from
            {schema}.outlier
        where
            idsegmento = :idSegmentOrigin
        ON CONFLICT (fkmedicamento, idsegmento, doseconv, frequenciadia) DO nothing
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
