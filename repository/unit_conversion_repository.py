"""Repository for unit conversion"""

from sqlalchemy import and_, func

from models.appendix import MeasureUnit, MeasureUnitConvert
from models.main import (
    Drug,
    DrugAttributes,
    Outlier,
    PrescriptionAgg,
    Substance,
    db,
)


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
        prescribed_units = prescribed_units.filter(
            PrescriptionAgg.idDrug == id_drug
        )
        current_units = current_units.filter(
            MeasureUnitConvert.idDrug == id_drug
        )
        price_units = price_units.filter(DrugAttributes.idDrug == id_drug)

    return prescribed_units.union(price_units, current_units).cte("units")


def get_unit_conversion_list(id_segment: int):
    """Returns a list of unit conversions for a given segment"""

    active_drugs = (
        db.session.query(
            Outlier.idDrug.label("idDrug"),
            func.sum(Outlier.countNum).label("prescribed_quantity"),
        )
        .group_by(Outlier.idDrug)
        .cte("active_drugs")
    )

    units = _build_units_cte()

    conversion_query = (
        db.session.query(
            func.count().over(),
            Drug.id,
            Drug.name,
            units.c.idMeasureUnit,
            MeasureUnitConvert.factor,
            MeasureUnit.description,
            Drug.sctid,
            Substance.default_measureunit,
            MeasureUnit.measureunit_nh,
            active_drugs.c.prescribed_quantity,
            Substance.tags,
        )
        .join(active_drugs, Drug.id == active_drugs.c.idDrug)
        .join(units, Drug.id == units.c.idDrug)
        .outerjoin(
            MeasureUnitConvert,
            and_(
                MeasureUnitConvert.idDrug == Drug.id,
                MeasureUnitConvert.idSegment == id_segment,
                MeasureUnitConvert.idMeasureUnit == units.c.idMeasureUnit,
            ),
        )
        .outerjoin(MeasureUnit, MeasureUnit.id == units.c.idMeasureUnit)
        .outerjoin(Substance, Drug.sctid == Substance.id)
    )

    return conversion_query.order_by(Drug.name, MeasureUnitConvert.factor).all()


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
