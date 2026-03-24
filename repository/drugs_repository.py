"""Repository: drugs related operations"""

from sqlalchemy import and_, func, or_

from models.appendix import MeasureUnit, MeasureUnitConvert
from models.main import (
    Drug,
    DrugAttributes,
    Outlier,
    Substance,
    User,
    db,
)
from models.requests.admin.admin_drug_request import AdminDrugListRequest
from models.segment import Segment


def get_admin_drug_list(request_data: AdminDrugListRequest):
    """Gets list of drugs with attributes and conversions for management"""
    SegmentOutlier = db.aliased(Segment)

    presc_query = (
        db.session.query(
            Outlier.idDrug.label("idDrug"),
            Outlier.idSegment.label("idSegment"),
            func.sum(Outlier.countNum).label("count"),
        )
        .group_by(Outlier.idDrug, Outlier.idSegment)
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
            presc_query.c.count.label("drug_count"),
            DrugAttributes.division,
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

    if request_data.hasSubstance != None:
        if request_data.hasSubstance:
            q = q.filter(Substance.id != None)
        else:
            q = q.filter(Substance.id == None)

    if request_data.hasDefaultUnit != None:
        if request_data.hasDefaultUnit:
            q = q.filter(DrugAttributes.idMeasureUnit != None)
        else:
            q = q.filter(DrugAttributes.idMeasureUnit == None)

    if request_data.minDrugCount is not None:
        q = q.filter(presc_query.c.count >= request_data.minDrugCount)

    if request_data.hasPriceUnit != None:
        if request_data.hasPriceUnit:
            q = q.filter(DrugAttributes.idMeasureUnitPrice != None)
        else:
            q = q.filter(DrugAttributes.idMeasureUnitPrice == None)

    if request_data.hasPriceConversion != None:
        if request_data.hasPriceConversion:
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

    if request_data.hasInconsistency != None:
        if request_data.hasInconsistency:
            q = q.filter(DrugAttributes.idDrug == None)
        else:
            q = q.filter(DrugAttributes.idDrug != None)

    if request_data.hasAISubstance != None:
        if request_data.hasAISubstance:
            q = q.filter(Drug.ai_accuracy != None)

            if (
                request_data.aiAccuracyRange != None
                and len(request_data.aiAccuracyRange) == 2
            ):
                q = q.filter(
                    Drug.ai_accuracy >= request_data.aiAccuracyRange[0]
                ).filter(Drug.ai_accuracy <= request_data.aiAccuracyRange[1])
        else:
            q = q.filter(Drug.ai_accuracy == None)

    if request_data.hasMaxDose != None:
        if request_data.hasMaxDose:
            q = q.filter(DrugAttributes.maxDose != None)
        else:
            q = q.filter(DrugAttributes.maxDose == None)

    if request_data.hasSubstanceMaxDoseWeightAdult != None:
        if request_data.hasSubstanceMaxDoseWeightAdult:
            q = q.filter(Substance.maxdose_adult_weight != None)
        else:
            q = q.filter(Substance.maxdose_adult_weight == None)

    if request_data.hasSubstanceMaxDoseWeightPediatric != None:
        if request_data.hasSubstanceMaxDoseWeightPediatric:
            q = q.filter(Substance.maxdose_pediatric_weight != None)
        else:
            q = q.filter(Substance.maxdose_pediatric_weight == None)

    if request_data.tpRefMaxDose != None:
        if request_data.tpRefMaxDose == "empty":
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
        elif request_data.tpRefMaxDose == "diff":
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
        elif request_data.tpRefMaxDose == "equal":
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

    if len(request_data.attributeList) > 0:
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
            ["use_weight", DrugAttributes.useWeight],
        ]

        for a in bool_attributes:
            if a[0] in request_data.attributeList:
                if request_data.tpAttributeList == "notin":
                    if str(a[1].type) == "BOOLEAN":
                        q = q.filter(or_(a[1] == False, a[1] == None))
                    else:
                        q = q.filter(a[1] == None)
                else:
                    if str(a[1].type) == "BOOLEAN":
                        q = q.filter(a[1] == True)
                    else:
                        q = q.filter(a[1] != None)

    if request_data.term:
        q = q.filter(Drug.name.ilike(request_data.term))

    if request_data.substance:
        q = q.filter(Substance.name.ilike(request_data.substance))

    if request_data.idSegmentList and len(request_data.idSegmentList) > 0:
        q = q.filter(DrugAttributes.idSegment.in_(request_data.idSegmentList))

    if request_data.substanceList:
        if request_data.tpSubstanceList == "in":
            q = q.filter(Substance.id.in_(request_data.substanceList))
        else:
            q = q.filter(~Substance.id.in_(request_data.substanceList))

    if request_data.idDrugList:
        q = q.filter(DrugAttributes.idDrug.in_(request_data.idDrugList))

    return (
        q.order_by(Drug.name, Segment.description)
        .limit(request_data.limit)
        .offset(request_data.offset)
        .all()
    )


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
