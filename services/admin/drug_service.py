from flask_api import status
from sqlalchemy import and_, or_, func

from models.main import *
from models.appendix import *
from models.segment import *
from models.enums import RoleEnum

from exception.validation_error import ValidationError


def get_conversion_list(
    has_substance=None,
    has_price_conversion=None,
    has_default_unit=None,
    term=None,
    limit=10,
    offset=0,
    id_segment_list=None,
):
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
            func.count().over(),
            Substance.name,
        )
        .select_from(Drug)
        .join(DrugAttributes, DrugAttributes.idDrug == Drug.id)
        .join(Segment, Segment.id == DrugAttributes.idSegment)
        .outerjoin(
            MeasureUnitConvert,
            and_(
                MeasureUnitConvert.idSegment == Segment.id,
                MeasureUnitConvert.idDrug == Drug.id,
                MeasureUnitConvert.idMeasureUnit == DrugAttributes.idMeasureUnitPrice,
            ),
        )
        .outerjoin(Substance, Drug.sctid == Substance.id)
    )

    if has_substance != None:
        if has_substance:
            q = q.filter(Drug.sctid != None)
        else:
            q = q.filter(Drug.sctid == None)

    if has_default_unit != None:
        if has_default_unit:
            q = q.filter(DrugAttributes.idMeasureUnit != None)
        else:
            q = q.filter(DrugAttributes.idMeasureUnit == None)

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

    if term:
        q = q.filter(Drug.name.ilike(term))

    if id_segment_list and len(id_segment_list) > 0:
        q = q.filter(DrugAttributes.idSegment.in_(id_segment_list))

    return q.order_by(Drug.name, Segment.description).limit(limit).offset(offset).all()


def update_price_factor(id_drug, id_segment, factor, user):
    roles = user.config["roles"] if user.config and "roles" in user.config else []
    if RoleEnum.ADMIN.value not in roles and RoleEnum.TRAINING.value not in roles:
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    attributes = (
        db.session.query(DrugAttributes)
        .filter(DrugAttributes.idDrug == id_drug)
        .filter(DrugAttributes.idSegment == id_segment)
        .first()
    )

    if attributes == None:
        raise ValidationError(
            "Registro inexistente", "errors.invalidRecord", status.HTTP_400_BAD_REQUEST
        )

    if attributes.idMeasureUnitPrice == None:
        raise ValidationError(
            "Medicamento não possui unidade de custo definida",
            "errors.invalidRecord",
            status.HTTP_400_BAD_REQUEST,
        )

    conversion = MeasureUnitConvert.query.get(
        (attributes.idMeasureUnitPrice, id_drug, id_segment)
    )

    if conversion is None:
        conversion = MeasureUnitConvert()
        conversion.idMeasureUnit = attributes.idMeasureUnitPrice
        conversion.idDrug = id_drug
        conversion.idSegment = id_segment
        conversion.factor = factor

        db.session.add(conversion)
    else:
        conversion.factor = factor

        db.session.flush()
