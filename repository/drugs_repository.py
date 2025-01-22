from sqlalchemy import and_, or_, func

from models.main import db, PrescriptionAgg, User
from models.prescription import (
    MeasureUnit,
    MeasureUnitConvert,
    Outlier,
    Drug,
    DrugAttributes,
    Substance,
)
from models.segment import Segment


def get_admin_drug_list(
    has_substance=None,
    has_price_conversion=None,
    has_default_unit=None,
    has_price_unit=None,
    has_inconsistency=None,
    has_missing_conversion=None,
    attribute_list=[],
    term=None,
    substance=None,
    limit=10,
    offset=0,
    id_segment_list=None,
    has_ai_substance=None,
    ai_accuracy_range=None,
    has_max_dose=None,
    source_list=None,
    tp_ref_max_dose=None,
    substance_list=[],
    tp_substance_list=None,
    id_drug_list=[],
):
    SegmentOutlier = db.aliased(Segment)
    ConversionsAgg = db.aliased(MeasureUnitConvert)
    MeasureUnitAgg = db.aliased(MeasureUnit)

    presc_query = (
        db.session.query(
            Outlier.idDrug.label("idDrug"), Outlier.idSegment.label("idSegment")
        )
        .group_by(Outlier.idDrug, Outlier.idSegment)
        .subquery()
    )

    conversions_query = (
        db.session.query(
            PrescriptionAgg.idDrug.label("idDrug"),
            PrescriptionAgg.idSegment.label("idSegment"),
        )
        .select_from(PrescriptionAgg)
        .join(
            MeasureUnitAgg,
            PrescriptionAgg.idMeasureUnit == MeasureUnitAgg.id,
        )
        .outerjoin(
            ConversionsAgg,
            and_(
                ConversionsAgg.idSegment == PrescriptionAgg.idSegment,
                ConversionsAgg.idDrug == PrescriptionAgg.idDrug,
                ConversionsAgg.idMeasureUnit == PrescriptionAgg.idMeasureUnit,
            ),
        )
        .filter(PrescriptionAgg.idSegment != None)
        .filter(PrescriptionAgg.idMeasureUnit != None)
        .filter(ConversionsAgg.factor == None)
        .group_by(PrescriptionAgg.idDrug, PrescriptionAgg.idSegment)
        .subquery()
    )

    q = (
        db.session.query(
            Drug.id,
            Drug.name,
            Segment.id,
            Segment.description,
            DrugAttributes.idMeasureUnit,
            DrugAttributes.idMeasureUnitPrice,
            DrugAttributes.price,
            Drug.sctid,
            MeasureUnitConvert.factor,
            func.count().over().label("total"),
            Substance.name,
            SegmentOutlier.description,
            Drug.ai_accuracy,
            DrugAttributes.maxDose,
            DrugAttributes.useWeight,
            MeasureUnit.description.label("measure_unit_default_name"),
            Segment.type.label("segment_type"),
            DrugAttributes.ref_maxdose,
            DrugAttributes.ref_maxdose_weight,
            Substance.maxdose_adult,
            Substance.maxdose_adult_weight,
            Substance.maxdose_pediatric,
            Substance.maxdose_pediatric_weight,
            Substance.default_measureunit,
            MeasureUnit.measureunit_nh,
            User.name.label("responsible"),
            DrugAttributes.update,
        )
        .select_from(presc_query)
        .join(Drug, presc_query.c.idDrug == Drug.id)
        .outerjoin(
            DrugAttributes,
            and_(
                DrugAttributes.idDrug == Drug.id,
                DrugAttributes.idSegment == presc_query.c.idSegment,
            ),
        )
        .outerjoin(MeasureUnit, MeasureUnit.id == DrugAttributes.idMeasureUnit)
        .outerjoin(Segment, Segment.id == DrugAttributes.idSegment)
        .outerjoin(
            MeasureUnitConvert,
            and_(
                MeasureUnitConvert.idSegment == Segment.id,
                MeasureUnitConvert.idDrug == Drug.id,
                MeasureUnitConvert.idMeasureUnit == DrugAttributes.idMeasureUnitPrice,
            ),
        )
        .outerjoin(Substance, Drug.sctid == Substance.id)
        .outerjoin(SegmentOutlier, SegmentOutlier.id == presc_query.c.idSegment)
        .outerjoin(User, User.id == DrugAttributes.user)
    )

    if has_missing_conversion:
        q = q.outerjoin(
            conversions_query,
            and_(
                conversions_query.c.idDrug == presc_query.c.idDrug,
                conversions_query.c.idSegment == presc_query.c.idSegment,
            ),
        ).filter(conversions_query.c.idDrug != None)

    if has_substance != None:
        if has_substance:
            q = q.filter(Substance.id != None)
        else:
            q = q.filter(Substance.id == None)

    if has_default_unit != None:
        if has_default_unit:
            q = q.filter(DrugAttributes.idMeasureUnit != None)
        else:
            q = q.filter(DrugAttributes.idMeasureUnit == None)

    if has_price_unit != None:
        if has_price_unit:
            q = q.filter(DrugAttributes.idMeasureUnitPrice != None)
        else:
            q = q.filter(DrugAttributes.idMeasureUnitPrice == None)

    if has_price_conversion != None:
        if has_price_conversion:
            q = q.filter(
                or_(
                    MeasureUnitConvert.factor != None,
                    DrugAttributes.idMeasureUnitPrice == DrugAttributes.idMeasureUnit,
                )
            )
        else:
            q = q.filter(
                and_(
                    MeasureUnitConvert.factor == None,
                    func.coalesce(DrugAttributes.idMeasureUnitPrice, "")
                    != func.coalesce(DrugAttributes.idMeasureUnit, ""),
                    DrugAttributes.idMeasureUnitPrice != None,
                )
            )

    if has_inconsistency != None:
        if has_inconsistency:
            q = q.filter(DrugAttributes.idDrug == None)
        else:
            q = q.filter(DrugAttributes.idDrug != None)

    if has_ai_substance != None:
        if has_ai_substance:
            q = q.filter(Drug.ai_accuracy != None)

            if ai_accuracy_range != None and len(ai_accuracy_range) == 2:
                q = q.filter(Drug.ai_accuracy >= ai_accuracy_range[0]).filter(
                    Drug.ai_accuracy <= ai_accuracy_range[1]
                )
        else:
            q = q.filter(Drug.ai_accuracy == None)

    if has_max_dose != None:
        if has_max_dose:
            q = q.filter(DrugAttributes.maxDose != None)
        else:
            q = q.filter(DrugAttributes.maxDose == None)

    if tp_ref_max_dose != None:
        if tp_ref_max_dose == "empty":
            q = q.filter(
                or_(
                    and_(
                        DrugAttributes.useWeight == True,
                        DrugAttributes.ref_maxdose_weight == None,
                    ),
                    and_(
                        or_(
                            DrugAttributes.useWeight == None,
                            DrugAttributes.useWeight == False,
                        ),
                        DrugAttributes.ref_maxdose == None,
                    ),
                )
            )
        elif tp_ref_max_dose == "diff":
            q = q.filter(
                or_(
                    and_(
                        DrugAttributes.useWeight == True,
                        DrugAttributes.ref_maxdose_weight != DrugAttributes.maxDose,
                    ),
                    and_(
                        or_(
                            DrugAttributes.useWeight == None,
                            DrugAttributes.useWeight == False,
                        ),
                        DrugAttributes.ref_maxdose != DrugAttributes.maxDose,
                    ),
                )
            )
        elif tp_ref_max_dose == "equal":
            q = q.filter(
                or_(
                    and_(
                        DrugAttributes.useWeight == True,
                        DrugAttributes.ref_maxdose_weight == DrugAttributes.maxDose,
                    ),
                    and_(
                        or_(
                            DrugAttributes.useWeight == None,
                            DrugAttributes.useWeight == False,
                        ),
                        DrugAttributes.ref_maxdose == DrugAttributes.maxDose,
                    ),
                )
            )

    if len(attribute_list) > 0:
        bool_attributes = [
            ["mav", DrugAttributes.mav],
            ["idoso", DrugAttributes.elderly],
            ["controlados", DrugAttributes.controlled],
            ["antimicro", DrugAttributes.antimicro],
            ["quimio", DrugAttributes.chemo],
            ["sonda", DrugAttributes.tube],
            ["naopadronizado", DrugAttributes.notdefault],
            ["linhabranca", DrugAttributes.whiteList],
            ["dialisavel", DrugAttributes.dialyzable],
            ["renal", DrugAttributes.kidney],
            ["hepatico", DrugAttributes.liver],
            ["plaquetas", DrugAttributes.platelets],
            ["dosemaxima", DrugAttributes.maxDose],
            ["risco_queda", DrugAttributes.fallRisk],
            ["lactante", DrugAttributes.lactating],
            ["gestante", DrugAttributes.pregnant],
            ["jejum", DrugAttributes.fasting],
        ]

        for a in bool_attributes:
            if a[0] in attribute_list:
                if str(a[1].type) == "BOOLEAN":
                    q = q.filter(a[1] == True)
                else:
                    q = q.filter(a[1] != None)

    if term:
        q = q.filter(Drug.name.ilike(term))

    if substance:
        q = q.filter(Substance.name.ilike(substance))

    if id_segment_list and len(id_segment_list) > 0:
        q = q.filter(DrugAttributes.idSegment.in_(id_segment_list))

    if source_list and len(source_list) > 0:
        q = q.filter(Drug.source.in_(source_list))

    if substance_list:
        if tp_substance_list == "in":
            q = q.filter(Substance.id.in_(substance_list))
        else:
            q = q.filter(~Substance.id.in_(substance_list))

    if id_drug_list:
        q = q.filter(DrugAttributes.idDrug.in_(id_drug_list))

    return q.order_by(Drug.name, Segment.description).limit(limit).offset(offset).all()


def get_drug_attributes(id_drug: int = None, id_segment: int = None):
    """
    Returns a list of drugs (with substances) from medatributos table
    """

    query = (
        db.session.query(DrugAttributes, Drug, Substance, Segment)
        .join(Drug, Drug.id == DrugAttributes.idDrug)
        .join(Substance, Drug.sctid == Substance.id)
        .join(Segment, Segment.id == DrugAttributes.idSegment)
    )

    if id_drug:
        query = query.filter(DrugAttributes.idDrug == id_drug)

    if id_segment:
        query = query.filter(DrugAttributes.idSegment == id_segment)

    return query.all()


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
