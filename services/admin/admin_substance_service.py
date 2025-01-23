from sqlalchemy import func, or_, cast
from sqlalchemy.orm import undefer
from datetime import datetime
from sqlalchemy.dialects import postgresql

from models.main import db, Substance, SubstanceClass, User
from models.requests.admin.admin_substance import AdminSubstanceRequest
from decorators.has_permission_decorator import has_permission, Permission
from exception.validation_error import ValidationError
from utils import status, dateutils


@has_permission(Permission.ADMIN_SUBSTANCES)
def get_substances(
    name=None,
    idClassList=[],
    has_class=None,
    has_admin_text=None,
    class_name=None,
    handling_option="filled",
    handling_type_list=[],
    limit=50,
    offset=0,
    has_max_dose_adult=None,
    has_max_dose_adult_weight=None,
    has_max_dose_pediatric=None,
    has_max_dose_pediatric_weight=None,
    tags=[],
    tp_substance_tag_list="in",
):

    q = (
        db.session.query(
            Substance, SubstanceClass, func.count().over().label("count"), User
        )
        .outerjoin(SubstanceClass, SubstanceClass.id == Substance.idclass)
        .outerjoin(User, Substance.updatedBy == User.id)
    )

    if name != None:
        q = q.filter(Substance.name.ilike(name))

    if class_name != None:
        q = q.filter(SubstanceClass.id.ilike(class_name))

    if len(idClassList) > 0:
        q = q.filter(Substance.idclass.in_(idClassList))

    if len(handling_type_list) > 0:
        handlings = []
        for h in handling_type_list:
            if handling_option == "filled":
                handlings.append(Substance.handling[h].astext != None)
            else:
                handlings.append(Substance.handling[h].astext == None)

        q = q.filter(or_(*handlings))

    if has_class != None:
        if has_class:
            q = q.filter(Substance.idclass != None)
        else:
            q = q.filter(Substance.idclass == None)

    if has_admin_text != None:
        if has_admin_text:
            q = q.filter(Substance.admin_text != None)
        else:
            q = q.filter(Substance.admin_text == None)

    if has_max_dose_adult != None:
        if has_max_dose_adult:
            q = q.filter(Substance.maxdose_adult != None)
        else:
            q = q.filter(Substance.maxdose_adult == None)

    if has_max_dose_adult_weight != None:
        if has_max_dose_adult_weight:
            q = q.filter(Substance.maxdose_adult_weight != None)
        else:
            q = q.filter(Substance.maxdose_adult_weight == None)

    if has_max_dose_pediatric != None:
        if has_max_dose_pediatric:
            q = q.filter(Substance.maxdose_pediatric != None)
        else:
            q = q.filter(Substance.maxdose_pediatric == None)

    if has_max_dose_pediatric_weight != None:
        if has_max_dose_pediatric_weight:
            q = q.filter(Substance.maxdose_pediatric_weight != None)
        else:
            q = q.filter(Substance.maxdose_pediatric_weight == None)

    if tags:
        if tp_substance_tag_list == "notin":
            q = q.filter(
                ~cast(tags, postgresql.ARRAY(db.String)).overlap(
                    func.coalesce(Substance.tags, [])
                )
            )
        else:
            q = q.filter(
                cast(tags, postgresql.ARRAY(db.String)).overlap(Substance.tags)
            )

    q = (
        q.options(undefer(Substance.handling), undefer(Substance.admin_text))
        .order_by(Substance.name)
        .limit(limit)
        .offset(offset)
    )

    results = q.all()

    if len(results) > 0:
        return {
            "count": results[0].count,
            "data": [
                dict(
                    _to_dto(i[0]),
                    **{
                        "className": i[1].name if i[1] != None else None,
                        "responsible": i.User.name if i.User else None,
                    }
                )
                for i in results
            ],
        }

    return {"count": 0, "data": []}


@has_permission(Permission.ADMIN_SUBSTANCES)
def upsert_substance(request_data: AdminSubstanceRequest, user_context: User):
    subs = db.session.query(Substance).filter(Substance.id == request_data.id).first()

    if subs is None:
        subs = Substance()
        subs.id = request_data.id
        db.session.add(subs)

    subs.name = request_data.name
    subs.idclass = request_data.idClass
    subs.active = request_data.active
    subs.link = request_data.link
    subs.handling = request_data.handling
    subs.admin_text = request_data.adminText
    subs.maxdose_adult = request_data.maxdoseAdult
    subs.maxdose_adult_weight = request_data.maxdoseAdultWeight
    subs.maxdose_pediatric = request_data.maxdosePediatric
    subs.maxdose_pediatric_weight = request_data.maxdosePediatricWeight
    subs.default_measureunit = request_data.defaultMeasureUnit
    subs.division_range = request_data.divisionRange
    subs.tags = request_data.tags
    subs.kidney_adult = request_data.kidneyAdult
    subs.kidney_pediatric = request_data.kidneyPediatric
    subs.liver_adult = request_data.liverAdult
    subs.liver_pediatric = request_data.liverPediatric
    subs.platelets = request_data.platelets
    subs.fall_risk = request_data.fallRisk
    subs.pregnant = request_data.pregnant
    subs.lactating = request_data.lactating

    if (
        subs.maxdose_adult
        or subs.maxdose_adult_weight
        or subs.maxdose_pediatric
        or subs.maxdose_pediatric_weight
    ) and not subs.default_measureunit:
        raise ValidationError(
            "Unidade de medida padrão deve ser especificada",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    if not subs.handling:
        subs.handling = None

    subs.updatedAt = datetime.today()
    subs.updatedBy = user_context.id

    db.session.flush()

    db_substance = (
        db.session.query(Substance, SubstanceClass, User)
        .outerjoin(SubstanceClass, SubstanceClass.id == Substance.idclass)
        .outerjoin(User, Substance.updatedBy == User.id)
        .filter(Substance.id == subs.id)
        .first()
    )

    return dict(
        _to_dto(db_substance[0]),
        **{
            "className": db_substance[1].name if db_substance[1] != None else None,
            "responsible": db_substance.User.name if db_substance.User else None,
        }
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
