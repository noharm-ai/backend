"""Repository: drugs related operations"""

from sqlalchemy import and_, func

from models.appendix import MeasureUnit, MeasureUnitConvert
from models.main import Drug, DrugAttributes, Substance, db
from models.prescription import Prescription, PrescriptionDrug


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


def get_recent_routes_and_intervals(id_drug: int, id_segment: int, days: int):
    """
    Distinct (route, interval, idFrequency) of the drug's items in the segment
    prescribed in the last days.

    One query serves both the routes and the intervals of the drug summary:
    each of them read the same presmed x prescricao join, and that join is
    what is slow on large schemas.
    """

    return (
        db.session.query(
            PrescriptionDrug.route,
            PrescriptionDrug.interval,
            PrescriptionDrug.idFrequency,
        )
        .select_from(PrescriptionDrug)
        .join(Prescription, Prescription.id == PrescriptionDrug.idPrescription)
        .filter(
            PrescriptionDrug.idDrug == id_drug,
            PrescriptionDrug.idSegment == id_segment,
            Prescription.date > func.current_date() - days,
        )
        .group_by(
            PrescriptionDrug.route,
            PrescriptionDrug.interval,
            PrescriptionDrug.idFrequency,
        )
        .all()
    )
