"""Repository: drugs related operations"""

from sqlalchemy import and_

from models.appendix import MeasureUnit, MeasureUnitConvert
from models.main import Drug, DrugAttributes, Substance, db


def get_single_drug(
    id_drug: int = None, id_segment: int = None
) -> (Drug, DrugAttributes, Substance):
    """
    Returns drug data with attributes and substance
    """

    return (
        db.session.query(Drug, DrugAttributes, Substance)
        .outerjoin(
            DrugAttributes,
            and_(
                Drug.id == DrugAttributes.idDrug, DrugAttributes.idSegment == id_segment
            ),
        )
        .outerjoin(Substance, Drug.sctid == Substance.id)
        .filter(Drug.id == id_drug)
        .first()
    )


def get_conversions(id_drug: int = None):
    """
    Returns all conversion records
    """

    query = db.session.query(MeasureUnitConvert, MeasureUnit).join(
        MeasureUnit, MeasureUnitConvert.idMeasureUnit == MeasureUnit.id
    )

    if id_drug:
        query = query.filter(MeasureUnitConvert.idDrug == id_drug)

    return query.order_by(MeasureUnitConvert.idDrug).all()


def get_substance(id_drug: int = None):
    """
    Returns substance for a single drug
    """

    return db.session.query(Substance).filter(Substance.id == id_drug).first()
