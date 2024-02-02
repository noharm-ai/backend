from sqlalchemy.sql import distinct
from sqlalchemy import func, and_

from models.main import *
from models.appendix import *
from models.segment import *
from services import permission_service
from exception.validation_error import ValidationError


def get_conversion_list(id_segment):
    active_drugs = db.session.query(distinct(Outlier.idDrug).label("idDrug")).cte(
        "active_drugs"
    )

    prescribed_units = (
        db.session.query(
            PrescriptionAgg.idDrug.label("idDrug"),
            PrescriptionAgg.idMeasureUnit.label("idMeasureUnit"),
        )
        .filter(PrescriptionAgg.idMeasureUnit != None)
        .filter(PrescriptionAgg.idMeasureUnit != "")
        .group_by(PrescriptionAgg.idDrug, PrescriptionAgg.idMeasureUnit)
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

    units = prescribed_units.union(price_units).cte("units")

    q = (
        db.session.query(
            func.count().over(),
            Drug.id,
            Drug.name,
            units.c.idMeasureUnit,
            MeasureUnitConvert.factor,
            MeasureUnit.description,
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
        .order_by(Drug.name, MeasureUnitConvert.factor)
        .all()
    )

    return q


def save_conversions(
    id_drug, id_segment, id_measure_unit_default, conversion_list, user
):
    if not permission_service.has_maintainer_permission(user):
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    if (
        id_drug == None
        or id_segment == None
        or id_measure_unit_default == None
        or conversion_list == None
        or len(conversion_list) == 0
    ):
        raise ValidationError(
            "Parâmetros inválidos",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )

    for uc in conversion_list:
        if uc["factor"] == None or uc["factor"] == 0:
            raise ValidationError(
                "Fator de conversão inválido",
                "errors.invalidParams",
                status.HTTP_400_BAD_REQUEST,
            )

    da = (
        db.session.query(DrugAttributes)
        .filter(DrugAttributes.idDrug == id_drug)
        .filter(DrugAttributes.idSegment == id_segment)
        .first()
    )
    if da == None:
        da = DrugAttributes()
        db.session.add(da)

        # pk
        da.idDrug = id_drug
        da.idSegment = id_segment
    else:
        if da.idMeasureUnit != id_measure_unit_default:
            raise ValidationError(
                "A alteração de Unidade Padrão deve ser executada através do Assistente para Geração de Escores.",
                "errors.businessRule",
                status.HTTP_400_BAD_REQUEST,
            )

    da.idMeasureUnit = id_measure_unit_default
    da.update = datetime.today()
    da.user = user.id

    db.session.flush()

    # set conversions
    _update_conversion_list(
        conversion_list=conversion_list, id_drug=id_drug, id_segment=id_segment
    )

    # update other segments
    rejected_segments = []
    updated_segments = []
    segments = db.session.query(Segment).all()

    for s in segments:
        if s.id == id_segment:
            updated_segments.append(s.description)
            continue

        # set drug attributes
        da = (
            db.session.query(DrugAttributes)
            .filter(DrugAttributes.idDrug == id_drug)
            .filter(DrugAttributes.idSegment == s.id)
            .first()
        )
        if (
            da != None
            and da.idMeasureUnit != None
            and da.idMeasureUnit != id_measure_unit_default
        ):
            # do not update
            rejected_segments.append(s.description)
            continue
        else:
            updated_segments.append(s.description)

        if da == None:
            da = DrugAttributes()
            db.session.add(da)

            # pk
            da.idDrug = id_drug
            da.idSegment = s.id

        da.idMeasureUnit = id_measure_unit_default
        da.update = datetime.today()
        da.user = user.id

        db.session.flush()

        # update conversions
        _update_conversion_list(
            conversion_list=conversion_list, id_drug=id_drug, id_segment=s.id
        )

    return {"updated": updated_segments, "rejected": rejected_segments}


def _update_conversion_list(conversion_list, id_drug, id_segment):
    for uc in conversion_list:
        conversion = (
            db.session.query(MeasureUnitConvert)
            .filter(MeasureUnitConvert.idDrug == id_drug)
            .filter(MeasureUnitConvert.idSegment == id_segment)
            .filter(MeasureUnitConvert.idMeasureUnit == uc["idMeasureUnit"])
            .first()
        )
        if conversion == None:
            conversion = MeasureUnitConvert()
            conversion.idDrug = id_drug
            conversion.idSegment = id_segment
            conversion.idMeasureUnit = uc["idMeasureUnit"]

            db.session.add(conversion)

        conversion.factor = uc["factor"]

        db.session.flush()
