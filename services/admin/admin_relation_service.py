from sqlalchemy import func, or_, and_
from datetime import datetime

from models.main import db, Substance, User, Relation
from decorators.has_permission_decorator import has_permission, Permission


@has_permission(Permission.ADMIN_SUBSTANCE_RELATIONS)
def get_relations(
    id_origin_list=[],
    id_destination_list=[],
    kind_list=[],
    level=None,
    relation_status=None,
    limit=50,
    offset=0,
):
    SubstA = db.aliased(Substance)
    SubstB = db.aliased(Substance)

    q = (
        db.session.query(Relation, SubstA, SubstB, func.count().over().label("count"))
        .outerjoin(SubstA, SubstA.id == Relation.sctida)
        .outerjoin(SubstB, SubstB.id == Relation.sctidb)
    )

    if len(id_origin_list) > 1:
        q = q.filter(
            and_(
                Relation.sctida.in_(id_origin_list), Relation.sctidb.in_(id_origin_list)
            ),
        )

    elif len(id_origin_list) == 1:
        q = q.filter(
            or_(
                Relation.sctida.in_(id_origin_list), Relation.sctidb.in_(id_origin_list)
            )
        )

    if len(id_destination_list) > 0:
        q = q.filter(Relation.sctidb.in_(id_destination_list))

    if len(kind_list) > 0:
        q = q.filter(Relation.kind.in_(kind_list))

    if level != None:
        q = q.filter(Relation.level == level)

    if relation_status != None:
        if relation_status == 1:
            q = q.filter(Relation.active == True)
        else:
            q = q.filter(Relation.active == False)

    q = q.order_by(SubstA.name, SubstB.name).limit(limit).offset(offset)

    results = q.all()

    if len(results) > 0:
        return {
            "count": results[0].count,
            "data": [
                dict(
                    _to_dto(i[0]),
                    **{
                        "originName": i[1].name if i[1] != None else None,
                        "destinationName": i[2].name if i[2] != None else None,
                    }
                )
                for i in results
            ],
        }

    return {"count": 0, "data": []}


@has_permission(Permission.ADMIN_SUBSTANCE_RELATIONS)
def upsert_relation(data: dict, user_context: User):
    relation = (
        db.session.query(Relation)
        .filter(Relation.sctida == data.get("sctida", None))
        .filter(Relation.sctidb == data.get("sctidb", None))
        .filter(Relation.kind == data.get("kind", None))
        .first()
    )

    if relation == None:
        relation = Relation()
        relation.sctida = data.get("sctida", None)
        relation.sctidb = data.get("sctidb", None)
        relation.kind = data.get("kind", None)
        relation.creator = user_context.id
        db.session.add(relation)

    if "text" in data.keys():
        relation.text = data.get("text", None)
    if "active" in data.keys():
        relation.active = bool(data.get("active", False))
    if "level" in data.keys():
        relation.level = data.get("level", None)

    relation.update = datetime.today()
    relation.user = user_context.id

    db.session.flush()

    SubstA = db.aliased(Substance)
    SubstB = db.aliased(Substance)

    db_relation = (
        db.session.query(Relation, SubstA, SubstB)
        .outerjoin(SubstA, SubstA.id == Relation.sctida)
        .outerjoin(SubstB, SubstB.id == Relation.sctidb)
        .filter(Relation.sctida == relation.sctida)
        .filter(Relation.sctidb == relation.sctidb)
        .filter(Relation.kind == relation.kind)
        .first()
    )

    return dict(
        _to_dto(db_relation[0]),
        **{
            "originName": db_relation[1].name if db_relation[1] != None else None,
            "destinationName": db_relation[2].name if db_relation[2] != None else None,
        }
    )


def _to_dto(r: Relation):
    return {
        "sctida": str(r.sctida),
        "sctidb": str(r.sctidb),
        "kind": r.kind,
        "text": r.text,
        "active": r.active,
        "level": r.level,
    }
