from models.main import db
from sqlalchemy import asc, distinct

from models.appendix import *
from models.prescription import *
from models.enums import DrugAdminSegment
from services import permission_service
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

    if division != None and division == 1:
        raise ValidationError(
            "Divisor de faixas deve ser diferente de 1",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )

    if measure_unit_list:
        for m in measure_unit_list:
            _setDrugUnit(id_drug, m["idMeasureUnit"], id_segment, m["fator"])

    drugAttr = DrugAttributes.query.get((id_drug, id_segment))

    if drugAttr is None:
        drugAttr = create_attributes_from_reference(
            id_drug=id_drug, id_segment=id_segment, user=user
        )

    drugAttr.idMeasureUnit = id_measure_unit
    drugAttr.division = division if division != 0 else None
    drugAttr.useWeight = use_weight
    drugAttr.update = datetime.today()
    drugAttr.user = user.id

    db.session.flush()


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


def get_attributes(id_segment, id_drug, user):
    drug = Drug.query.get(id_drug)

    if drug == None:
        raise ValidationError(
            "Parâmetro inválido",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )

    attr = DrugAttributes.query.get((id_drug, id_segment))
    drug_ref = None
    if drug.sctid != None and permission_service.has_maintainer_permission(user):
        drug_ref = Notes.getDefaultNote(drug.sctid)

    if attr == None:
        return {"drugRef": drug_ref}

    return {
        "antimicro": attr.antimicro,
        "mav": attr.mav,
        "controlled": attr.controlled,
        "notdefault": attr.notdefault,
        "maxDose": attr.maxDose,
        "kidney": attr.kidney,
        "liver": attr.liver,
        "platelets": attr.platelets,
        "elderly": attr.elderly,
        "tube": attr.tube,
        "division": attr.division,
        "useWeight": attr.useWeight,
        "idMeasureUnit": attr.idMeasureUnit,
        "idMeasureUnitPrice": attr.idMeasureUnitPrice,
        "amount": attr.amount,
        "amountUnit": attr.amountUnit,
        "price": attr.price,
        "maxTime": attr.maxTime,
        "fallRisk": attr.fallRisk,
        "whiteList": attr.whiteList,
        "chemo": attr.chemo,
        "sctid": str(drug.sctid),
        "drugRef": drug_ref,
        "dialyzable": attr.dialyzable,
        "pregnant": attr.pregnant,
        "lactating": attr.lactating,
    }


def save_attributes(id_segment, id_drug, data, user):
    if id_drug == None or id_segment == None:
        raise ValidationError(
            "Parâmetro inválido",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )

    attr = DrugAttributes.query.get((id_drug, id_segment))
    add = False
    if attr is None:
        add = True
        attr = DrugAttributes()
        attr.idDrug = id_drug
        attr.idSegment = id_segment

    if "antimicro" in data.keys():
        attr.antimicro = bool(data.get("antimicro", 0))
    if "mav" in data.keys():
        attr.mav = bool(data.get("mav", 0))
    if "controlled" in data.keys():
        attr.controlled = bool(data.get("controlled", 0))
    if "idMeasureUnit" in data.keys():
        attr.idMeasureUnit = data.get("idMeasureUnit", None)
    if "notdefault" in data.keys():
        attr.notdefault = data.get("notdefault", 0)
    if "maxDose" in data.keys():
        attr.maxDose = data.get("maxDose", None)
        if attr.maxDose == "":
            attr.maxDose = None
    if "kidney" in data.keys():
        attr.kidney = data.get("kidney", None)
        if attr.kidney == "":
            attr.kidney = None
    if "liver" in data.keys():
        attr.liver = data.get("liver", None)
        if attr.liver == "":
            attr.liver = None
    if "platelets" in data.keys():
        attr.platelets = data.get("platelets", None)
        if attr.platelets == "":
            attr.platelets = None
    if "elderly" in data.keys():
        attr.elderly = data.get("elderly", 0)
    if "chemo" in data.keys():
        attr.chemo = data.get("chemo", 0)
    if "tube" in data.keys():
        attr.tube = data.get("tube", 0)
    if "division" in data.keys():
        attr.division = data.get("division", None)
    if "price" in data.keys():
        attr.price = data.get("price", None)
        if attr.price == "":
            attr.price = None
    if "maxTime" in data.keys():
        attr.maxTime = data.get("maxTime", None)
    if "fallRisk" in data.keys():
        attr.fallRisk = data.get("fallRisk", None)
    if "useWeight" in data.keys():
        attr.useWeight = data.get("useWeight", 0)
    if "amount" in data.keys():
        attr.amount = data.get("amount", None)
        if attr.amount == "":
            attr.amount = None
    if "amountUnit" in data.keys():
        attr.amountUnit = data.get("amountUnit", None)
    if "whiteList" in data.keys():
        attr.whiteList = data.get("whiteList", None)
        if not attr.whiteList:
            attr.whiteList = None
    if "dialyzable" in data.keys():
        attr.dialyzable = bool(data.get("dialyzable", 0))
    if "pregnant" in data.keys():
        attr.pregnant = data.get("pregnant", None)
    if "lactating" in data.keys():
        attr.lactating = data.get("lactating", None)

    attr.update = datetime.today()
    attr.user = user.id

    if add:
        db.session.add(attr)

    db.session.flush()


def update_substance(id_drug, sctid, user):
    drug = Drug.query.get(id_drug)

    if drug == None:
        raise ValidationError(
            "Registro inexistente", "errors.invalidRecord", status.HTTP_400_BAD_REQUEST
        )

    drug.sctid = sctid
    drug.ai_accuracy = None
    drug.updated_at = datetime.today()
    drug.updated_by = user.id

    db.session.flush()

    copy_substance_default_attributes(drug.id, drug.sctid, user)


def copy_substance_default_attributes(id_drug, sctid, user: User, overwrite=True):
    reference = (
        db.session.query(DrugAttributesReference)
        .filter(DrugAttributesReference.idDrug == sctid)
        .filter(DrugAttributesReference.idSegment == DrugAdminSegment.ADULT.value)
        .first()
    )

    if reference != None:
        segments = db.session.query(Segment).all()

        for s in segments:
            add = False
            da = (
                db.session.query(DrugAttributes)
                .filter(DrugAttributes.idDrug == id_drug)
                .filter(DrugAttributes.idSegment == s.id)
                .first()
            )
            if da == None:
                add = True
                da = DrugAttributes()

                # pk
                da.idDrug = id_drug
                da.idSegment = s.id
            elif not overwrite:
                continue

            # attributes
            da.antimicro = reference.antimicro
            da.mav = reference.mav
            da.controlled = reference.controlled
            da.tube = reference.tube
            da.chemo = reference.chemo
            da.elderly = reference.elderly
            da.whiteList = reference.whiteList
            da.dialyzable = reference.dialyzable

            da.kidney = reference.kidney
            da.liver = reference.liver
            da.platelets = reference.platelets
            da.fallRisk = reference.fallRisk
            da.lactating = reference.lactating
            da.pregnant = reference.pregnant

            # controls
            da.update = datetime.today()
            da.user = user.id

            if add:
                db.session.add(da)
            else:
                db.session.flush()


def create_attributes_from_reference(id_drug, id_segment, user):
    da = (
        db.session.query(DrugAttributes)
        .filter(DrugAttributes.idDrug == id_drug)
        .filter(DrugAttributes.idSegment == id_segment)
        .first()
    )
    drug = db.session.query(Drug).filter(Drug.id == id_drug).first()
    if drug == None:
        raise ValidationError(
            "Registro inexistente", "errors.invalidRecord", status.HTTP_400_BAD_REQUEST
        )

    reference = (
        db.session.query(DrugAttributesReference)
        .filter(DrugAttributesReference.idDrug == drug.sctid)
        .filter(DrugAttributesReference.idSegment == DrugAdminSegment.ADULT.value)
        .first()
    )

    if da == None:
        da = DrugAttributes()

        # pk
        da.idDrug = id_drug
        da.idSegment = id_segment

        if reference != None:
            # attributes
            da.antimicro = reference.antimicro
            da.mav = reference.mav
            da.controlled = reference.controlled
            da.tube = reference.tube
            da.chemo = reference.chemo
            da.elderly = reference.elderly
            da.whiteList = reference.whiteList
            da.dialyzable = reference.dialyzable

            da.kidney = reference.kidney
            da.liver = reference.liver
            da.platelets = reference.platelets
            da.fallRisk = reference.fallRisk
            da.lactating = reference.lactating
            da.pregnant = reference.pregnant

        # controls
        da.update = datetime.today()
        da.user = user.id

        db.session.add(da)
        db.session.flush()

        return da

    return None
