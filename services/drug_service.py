from models.main import db
from sqlalchemy import asc, distinct

from models.appendix import *
from models.prescription import *

from exception.validation_error import ValidationError


# MEASURE UNIT
def getPreviouslyPrescribedUnits(idDrug, idSegment):
    u = db.aliased(MeasureUnit)
    agg = db.aliased(PrescriptionAgg)

    return (
        db.session.query(
            u.id, u.description, func.sum(func.coalesce(agg.countNum, 0)).label("count")
        )
        .select_from(u)
        .outerjoin(
            agg,
            and_(
                agg.idMeasureUnit == u.id,
                agg.idDrug == idDrug,
                agg.idSegment == idSegment,
            ),
        )
        .filter(agg.idSegment == idSegment)
        .group_by(u.id, u.description, agg.idMeasureUnit)
        .order_by(asc(u.description))
        .all()
    )


def getUnits(idHospital):
    return (
        db.session.query(MeasureUnit)
        .filter(MeasureUnit.idHospital == idHospital)
        .order_by(asc(MeasureUnit.description))
        .all()
    )


# FREQUENCY
def getPreviouslyPrescribedFrequencies(idDrug, idSegment):
    agg = db.aliased(PrescriptionAgg)
    f = db.aliased(Frequency)

    return (
        db.session.query(
            f.id, f.description, func.sum(func.coalesce(agg.countNum, 0)).label("count")
        )
        .select_from(f)
        .outerjoin(
            agg,
            and_(
                agg.idFrequency == f.id,
                agg.idDrug == idDrug,
                agg.idSegment == idSegment,
            ),
        )
        .filter(agg.idSegment == idSegment)
        .group_by(f.id, f.description, agg.idFrequency)
        .order_by(asc(f.description))
        .all()
    )


def getFrequencies(idHospital):
    return (
        db.session.query(Frequency)
        .filter(Frequency.idHospital == idHospital)
        .order_by(asc(Frequency.description))
        .all()
    )


def get_all_frequencies():
    return (
        db.session.query(distinct(Frequency.id), Frequency.description)
        .select_from(Frequency)
        .order_by(asc(Frequency.description))
        .all()
    )


def drug_config_to_generate_score(
    id_drug, id_segment, id_measure_unit, division, use_weight, measure_unit_list, user
):
    if id_measure_unit == None or id_measure_unit == "":
        raise ValidationError(
            "Unidade de medida inválida",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )

    if division != None and division <= 1:
        raise ValidationError(
            "Divisor de faixas deve ser maior que 1",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )

    if measure_unit_list:
        for m in measure_unit_list:
            _setDrugUnit(id_drug, m["idMeasureUnit"], id_segment, m["fator"])

    drugAttr = DrugAttributes.query.get((id_drug, id_segment))

    newDrugAttr = False
    if drugAttr is None:
        newDrugAttr = True
        drugAttr = DrugAttributes()
        drugAttr.idDrug = id_drug
        drugAttr.idSegment = id_segment

    drugAttr.idMeasureUnit = id_measure_unit
    drugAttr.division = division if division != 0 else None
    drugAttr.useWeight = use_weight
    drugAttr.update = datetime.today()
    drugAttr.user = user.id

    if newDrugAttr:
        db.session.add(drugAttr)


def _setDrugUnit(idDrug, idMeasureUnit, idSegment, factor):
    u = MeasureUnitConvert.query.get((idMeasureUnit, idDrug, idSegment))
    new = False

    if u is None:
        new = True
        u = MeasureUnitConvert()
        u.idMeasureUnit = idMeasureUnit
        u.idDrug = idDrug
        u.idSegment = idSegment

    u.factor = factor

    if new:
        db.session.add(u)
