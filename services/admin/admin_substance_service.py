from models.main import Substance
from decorators.has_permission_decorator import has_permission, Permission
from exception.validation_error import ValidationError
from repository import substance_repository
from utils import status, dateutils


@has_permission(Permission.ADMIN_SUBSTANCES)
def get_substance(substance_id: int):
    db_substance = substance_repository.get_by_id(substance_id)

    if db_substance is None:
        raise ValidationError(
            "Substância não encontrada",
            "errors.notFound",
            status.HTTP_404_NOT_FOUND,
        )

    return dict(
        _to_dto(db_substance[0]),
        **{
            "className": db_substance[1].name if db_substance[1] is not None else None,
            "responsible": db_substance.User.name if db_substance.User else None,
        },
    )


def _to_dto(s: Substance):
    return {
        "id": str(s.id),
        "name": s.name,
        "idClass": s.idclass,
        "active": s.active,
        "link": s.link,
        "handling": s.handling,
        "adminText": s.admin_text,
        "maxdoseAdult": s.maxdose_adult,
        "maxdoseAdultWeight": s.maxdose_adult_weight,
        "maxdosePediatric": s.maxdose_pediatric,
        "maxdosePediatricWeight": s.maxdose_pediatric_weight,
        "defaultMeasureUnit": s.default_measureunit,
        "updatedAt": dateutils.to_iso(s.updatedAt),
        "tags": s.tags,
        "divisionRange": s.division_range,
        "kidneyAdult": s.kidney_adult,
        "kidneyPediatric": s.kidney_pediatric,
        "liverAdult": s.liver_adult,
        "liverPediatric": s.liver_pediatric,
        "platelets": s.platelets,
        "fallRisk": s.fall_risk,
        "pregnant": s.pregnant,
        "lactating": s.lactating,
    }
