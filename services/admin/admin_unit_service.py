from utils import status
from sqlalchemy import asc

from models.main import db
from models.appendix import MeasureUnit
from decorators.has_permission_decorator import has_permission, Permission
from exception.validation_error import ValidationError


@has_permission(Permission.ADMIN_UNIT)
def get_units(has_measureunit_nh=None):
    q = db.session.query(MeasureUnit)

    if has_measureunit_nh != None:
        if has_measureunit_nh:
            q = q.filter(MeasureUnit.measureunit_nh != None)
        else:
            q = q.filter(MeasureUnit.measureunit_nh == None)

    return q.order_by(asc(MeasureUnit.description)).all()


@has_permission(Permission.ADMIN_UNIT)
def update_unit(id: str, measureunit_nh: str):
    unit: MeasureUnit = (
        db.session.query(MeasureUnit).filter(MeasureUnit.id == id).first()
    )
    if unit is None:
        raise ValidationError(
            "Registro inexistente", "errors.invalidRecord", status.HTTP_400_BAD_REQUEST
        )

    unit.measureunit_nh = measureunit_nh

    db.session.add(unit)
    db.session.flush()

    return unit


def list_to_dto(units: list[MeasureUnit]):
    list = []

    for u in units:
        list.append(
            {"id": u.id, "name": u.description, "measureUnitNh": u.measureunit_nh}
        )

    return list
