"""Repository for unit conversion"""

from sqlalchemy import and_, func

from models.appendix import MeasureUnit, MeasureUnitConvert
from models.main import (
    Drug,
    DrugAttributes,
    PrescriptionAgg,
    Substance,
    db,
)
from models.prescription import Prescription, PrescriptionDrug
from models.segment import Segment

RECENT_PRESCRIBED_UNITS_DAYS = 15


def _build_units_cte(id_drug=None):
    """Builds a CTE combining all possible measure units for drugs from three sources."""

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

    if id_drug is not None:
        prescribed_units = prescribed_units.filter(PrescriptionAgg.idDrug == id_drug)
        current_units = current_units.filter(MeasureUnitConvert.idDrug == id_drug)
        price_units = price_units.filter(DrugAttributes.idDrug == id_drug)

        # presmed is too big to scan for every drug, only for a single one
        return prescribed_units.union(
            price_units,
            current_units,
            _build_recent_prescribed_units(id_drug=id_drug),
        ).cte("units")

    return prescribed_units.union(price_units, current_units).cte("units")


def _build_recent_prescribed_units(id_drug: int):
    """Measure units used in recent presmed records for a drug.

    Filters by fkmedicamento and idsegmento so the (fkmedicamento, idsegmento)
    index is used instead of a full scan on presmed.
    """
    return (
        db.session.query(
            PrescriptionDrug.idDrug.label("idDrug"),
            PrescriptionDrug.idMeasureUnit.label("idMeasureUnit"),
        )
        .join(Prescription, Prescription.id == PrescriptionDrug.idPrescription)
        .filter(PrescriptionDrug.idDrug == id_drug)
        .filter(PrescriptionDrug.idSegment.in_(db.session.query(Segment.id)))
        .filter(Prescription.date > func.current_date() - RECENT_PRESCRIBED_UNITS_DAYS)
        .filter(PrescriptionDrug.idMeasureUnit != None)
        .filter(PrescriptionDrug.idMeasureUnit != "")
        .group_by(PrescriptionDrug.idDrug, PrescriptionDrug.idMeasureUnit)
    )


def get_drugattributes_default_measure_unit_for_drug(id_drug: int):
    """Returns the default measure unit defined in medatributos table"""
    return (
        db.session.query(
            DrugAttributes.idMeasureUnit,
            MeasureUnit.measureunit_nh,
        )
        .outerjoin(MeasureUnit, MeasureUnit.id == DrugAttributes.idMeasureUnit)
        .filter(DrugAttributes.idDrug == id_drug)
        .filter(DrugAttributes.idMeasureUnit.is_not(None))
        .group_by(DrugAttributes.idMeasureUnit, MeasureUnit.measureunit_nh)
        .all()
    )


def get_substance_default_measure_unit_for_drug(id_drug: int) -> str | None:
    """Returns the substance default measure unit for a given drug (via Drug.sctid → Substance)"""
    return (
        db.session.query(Substance.default_measureunit)
        .join(Drug, Drug.sctid == Substance.id)
        .filter(Drug.id == id_drug)
        .scalar()
    )


def get_unit_conversion_for_drug(id_drug: int):
    """Returns unit conversion possibilities for a single drug (best factor across all segments)"""

    units = _build_units_cte(id_drug=id_drug)

    min_convert = (
        db.session.query(
            MeasureUnitConvert.idDrug.label("idDrug"),
            MeasureUnitConvert.idMeasureUnit.label("idMeasureUnit"),
            func.min(MeasureUnitConvert.factor).label("factor"),
        )
        .filter(MeasureUnitConvert.idDrug == id_drug)
        .group_by(MeasureUnitConvert.idDrug, MeasureUnitConvert.idMeasureUnit)
        .subquery()
    )

    return (
        db.session.query(
            Drug.id,
            Drug.name,
            units.c.idMeasureUnit,
            min_convert.c.factor,
            MeasureUnit.description,
            Drug.sctid,
            Substance.default_measureunit,
            MeasureUnit.measureunit_nh,
            Substance.tags,
        )
        .filter(Drug.id == id_drug)
        .join(units, Drug.id == units.c.idDrug)
        .outerjoin(
            min_convert,
            and_(
                min_convert.c.idDrug == Drug.id,
                min_convert.c.idMeasureUnit == units.c.idMeasureUnit,
            ),
        )
        .outerjoin(MeasureUnit, MeasureUnit.id == units.c.idMeasureUnit)
        .outerjoin(Substance, Drug.sctid == Substance.id)
        .order_by(Drug.name, min_convert.c.factor)
        .all()
    )
