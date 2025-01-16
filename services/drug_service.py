from sqlalchemy import asc, distinct, func, and_
from sqlalchemy.orm import undefer
from typing import List
from datetime import datetime

from models.main import (
    db,
    User,
    PrescriptionAgg,
    DrugAttributesReference,
    DrugAttributesAudit,
)
from models.prescription import (
    Drug,
    MeasureUnit,
    Prescription,
    PrescriptionDrug,
    Frequency,
    DrugAttributes,
    MeasureUnitConvert,
    Substance,
)
from models.segment import Segment
from models.enums import DrugAdminSegment, DrugAttributesAuditTypeEnum
from services import data_authorization_service
from services.admin import admin_drug_service
from exception.validation_error import ValidationError
from decorators.has_permission_decorator import has_permission, Permission
from utils import status, prescriptionutils


@has_permission(Permission.READ_PRESCRIPTION)
def get_drug_summary(id_drug: int, id_segment: int, complete=False):
    drug = Drug.query.get(id_drug)

    prescribedUnits = getPreviouslyPrescribedUnits(id_drug, id_segment)
    allUnits = getUnits()

    unitResults = []
    for u in prescribedUnits:
        unitResults.append(
            {"id": u.id, "description": u.description, "amount": u.count}
        )
    for u in allUnits:
        unitResults.append({"id": u.id, "description": u.description, "amount": 0})

    prescribedFrequencies = getPreviouslyPrescribedFrequencies(id_drug, id_segment)
    allFrequencies = getFrequencies()

    frequencyResults = []
    for f in prescribedFrequencies:
        frequencyResults.append(
            {"id": f.id, "description": f.description, "amount": f.count}
        )
    for f in allFrequencies:
        frequencyResults.append({"id": f.id, "description": f.description, "amount": 0})

    routeResults = []
    intervalResults = []

    if complete:
        max_days = 90
        routes = (
            db.session.query(PrescriptionDrug.route)
            .select_from(PrescriptionDrug)
            .join(Prescription, Prescription.id == PrescriptionDrug.idPrescription)
            .filter(
                and_(
                    PrescriptionDrug.idDrug == id_drug,
                    PrescriptionDrug.idSegment == id_segment,
                    Prescription.date > func.current_date() - max_days,
                )
            )
            .group_by(PrescriptionDrug.route)
            .all()
        )

        routeResults = []
        for r in routes:
            routeResults.append({"id": r.route, "description": r.route})

        intervals = (
            db.session.query(PrescriptionDrug.interval, PrescriptionDrug.idFrequency)
            .select_from(PrescriptionDrug)
            .join(Prescription, Prescription.id == PrescriptionDrug.idPrescription)
            .filter(
                and_(
                    PrescriptionDrug.idDrug == id_drug,
                    PrescriptionDrug.idSegment == id_segment,
                    Prescription.date > func.current_date() - max_days,
                    PrescriptionDrug.interval != None,
                )
            )
            .group_by(PrescriptionDrug.interval, PrescriptionDrug.idFrequency)
            .all()
        )

        intervalResults = []
        for i in intervals:
            intervalResults.append(
                {
                    "id": i.interval,
                    "idFrequency": i.idFrequency,
                    "description": prescriptionutils.timeValue(i.interval),
                }
            )

    return {
        "drug": {"id": int(id_drug), "name": drug.name if drug else ""},
        "units": unitResults,
        "frequencies": frequencyResults,
        "routes": routeResults,
        "intervals": intervalResults,
    }


@has_permission(Permission.READ_PRESCRIPTION)
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


@has_permission(Permission.READ_PRESCRIPTION)
def getUnits():
    return db.session.query(MeasureUnit).order_by(asc(MeasureUnit.description)).all()


@has_permission(Permission.READ_PRESCRIPTION)
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


@has_permission(Permission.READ_PRESCRIPTION)
def getFrequencies():
    return db.session.query(Frequency).order_by(asc(Frequency.description)).all()


@has_permission(Permission.READ_PRESCRIPTION)
def get_all_frequencies():
    return (
        db.session.query(distinct(Frequency.id), Frequency.description)
        .select_from(Frequency)
        .order_by(asc(Frequency.description))
        .all()
    )


@has_permission(Permission.WRITE_DRUG_ATTRIBUTES)
def drug_config_to_generate_score(
    id_drug,
    id_segment,
    id_measure_unit,
    division,
    use_weight,
    measure_unit_list,
    user_context: User,
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

    if not data_authorization_service.has_segment_authorization(
        id_segment=id_segment, user=user_context
    ):
        raise ValidationError(
            "Usuário não autorizado neste segmento",
            "errors.businessRules",
            status.HTTP_401_UNAUTHORIZED,
        )

    if measure_unit_list:
        for m in measure_unit_list:
            _setDrugUnit(id_drug, m["idMeasureUnit"], id_segment, m["fator"])

    drugAttr = DrugAttributes.query.get((id_drug, id_segment))

    if drugAttr is None:
        drugAttr = create_attributes_from_reference(
            id_drug=id_drug, id_segment=id_segment, user=user_context
        )

    drugAttr.idMeasureUnit = id_measure_unit
    drugAttr.division = division if division != 0 else None
    drugAttr.useWeight = use_weight
    drugAttr.update = datetime.today()
    drugAttr.user = user_context.id

    _audit(
        drug_attributes=drugAttr,
        audit_type=DrugAttributesAuditTypeEnum.UPSERT_BEFORE_GEN_SCORE,
        user=user_context,
    )

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


@has_permission(Permission.READ_PRESCRIPTION)
def get_attributes(id_segment, id_drug, user_permissions: List[Permission]):
    drug = Drug.query.get(id_drug)

    if drug == None:
        raise ValidationError(
            "Parâmetro inválido",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )

    attr = DrugAttributes.query.get((id_drug, id_segment))
    drug_ref = None
    if drug.sctid != None and Permission.ADMIN_DRUGS in user_permissions:
        subst = (
            db.session.query(Substance)
            .filter(Substance.id == drug.sctid)
            .options(undefer(Substance.admin_text))
            .first()
        )

        if subst != None:
            drug_ref = subst.admin_text

    if attr == None:
        return {"drugRef": drug_ref}

    result = to_dict(attr)
    result["sctid"] = str(drug.sctid)
    result["drugRef"] = drug_ref

    return result


@has_permission(Permission.WRITE_DRUG_ATTRIBUTES)
def save_attributes(id_segment, id_drug, data, user_context: User):
    if id_drug == None or id_segment == None:
        raise ValidationError(
            "Parâmetro inválido",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )

    if not data_authorization_service.has_segment_authorization(
        id_segment=id_segment, user=user_context
    ):
        raise ValidationError(
            "Usuário não autorizado neste segmento",
            "errors.businessRules",
            status.HTTP_401_UNAUTHORIZED,
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
    if "fasting" in data.keys():
        attr.fasting = data.get("fasting", None)

    attr.update = datetime.today()
    attr.user = user_context.id

    if add:
        db.session.add(attr)

    _audit(
        drug_attributes=attr,
        audit_type=DrugAttributesAuditTypeEnum.UPSERT,
        user=user_context,
    )

    db.session.flush()


@has_permission(Permission.WRITE_DRUG_ATTRIBUTES)
def update_substance(id_drug, sctid, user_context: User):
    drug = db.session.query(Drug).filter(Drug.id == id_drug).first()

    if drug == None:
        raise ValidationError(
            "Registro inexistente", "errors.invalidRecord", status.HTTP_400_BAD_REQUEST
        )

    drug.sctid = sctid
    drug.ai_accuracy = None
    drug.updated_at = datetime.today()
    drug.updated_by = user_context.id

    db.session.flush()

    copy_substance_default_attributes(
        drug.id, drug.sctid, user=user_context, calc_dose_max=True
    )

    return admin_drug_service.get_drug_list(id_drug_list=[id_drug], limit=20, offset=0)


# TODO: check where is called
def copy_substance_default_attributes(
    id_drug, sctid, user: User, overwrite=True, calc_dose_max=False
):
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
            da.fasting = reference.fasting

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

            if calc_dose_max:
                admin_drug_service.calculate_dosemax_uniq(
                    id_drug=id_drug, id_segment=da.idSegment
                )

            _audit(
                drug_attributes=da,
                audit_type=DrugAttributesAuditTypeEnum.UPSERT_UPDATE_SUBSTANCE,
                user=user,
            )


# TODO: called from other services
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
            da.fasting = reference.fasting

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

        _audit(
            drug_attributes=da,
            audit_type=DrugAttributesAuditTypeEnum.INSERT_FROM_REFERENCE,
            user=user,
        )

        return da

    return None


def to_dict(attr: DrugAttributes):
    if attr == None:
        return None

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
        "dialyzable": attr.dialyzable,
        "pregnant": attr.pregnant,
        "lactating": attr.lactating,
        "fasting": attr.fasting,
    }


def _audit(
    drug_attributes: DrugAttributes, audit_type: DrugAttributesAuditTypeEnum, user: User
):
    audit = DrugAttributesAudit()
    audit.idDrug = drug_attributes.idDrug
    audit.idSegment = drug_attributes.idSegment
    audit.auditType = audit_type.value
    audit.extra = to_dict(drug_attributes)
    audit.createdAt = datetime.today()
    audit.createdBy = user.id

    db.session.add(audit)


@has_permission(Permission.WRITE_DRUG_ATTRIBUTES)
def update_convert_factor(
    id_measure_unit: str, id_drug: int, id_segment: int, factor: float
):
    if factor == 0:
        raise ValidationError(
            "Fator de conversão deve ser maior que zero.",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    u = (
        db.session.query(MeasureUnitConvert)
        .filter(
            MeasureUnitConvert.idMeasureUnit == id_measure_unit,
            MeasureUnitConvert.idDrug == id_drug,
            MeasureUnitConvert.idSegment == id_segment,
        )
        .first()
    )
    new = False

    if u is None:
        new = True
        u = MeasureUnitConvert()
        u.idMeasureUnit = id_measure_unit
        u.idDrug = id_drug
        u.idSegment = id_segment

    u.factor = factor

    if new:
        db.session.add(u)
