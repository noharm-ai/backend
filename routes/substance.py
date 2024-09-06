from models.main import *
from models.prescription import *
from flask import Blueprint, request
from markupsafe import escape as escape_html
from flask_jwt_extended import jwt_required, get_jwt_identity
from .utils import tryCommit

from services import substance_service
from exception.validation_error import ValidationError

app_sub = Blueprint("app_sub", __name__)


@app_sub.route("/substance", methods=["GET"])
@jwt_required()
def getSubstance():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    drugs = Substance.query.order_by(asc(Substance.name)).all()

    results = []
    for d in drugs:
        results.append(
            {
                "sctid": str(d.id),
                "name": d.name.upper(),
                "idclass": d.idclass,
                "active": d.active,
            }
        )

    results.sort(key=sortSubstance)

    return {"status": "success", "data": results}, status.HTTP_200_OK


@app_sub.route("/substance/single/<int:idSubstance>", methods=["GET"])
@jwt_required()
def get_substance_single(idSubstance):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    subs = Substance.query.get(idSubstance)

    return {
        "status": "success",
        "data": {
            "sctid": subs.id,
            "name": subs.name.upper(),
            "idclass": subs.idclass,
            "active": subs.active,
        },
    }, status.HTTP_200_OK


@app_sub.route("/substance/handling", methods=["GET"])
@jwt_required()
def get_substance_handling():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    try:
        result = substance_service.get_substance_handling(
            sctid=request.args.get("sctid", None),
            alert_type=request.args.get("alertType"),
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return {
        "status": "success",
        "data": result,
    }, status.HTTP_200_OK


@app_sub.route("/substance/find", methods=["GET"])
@jwt_required()
def find_substance():
    term = request.args.get("term", "")
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    try:
        results = substance_service.find_substance(term)
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return {
        "status": "success",
        "data": results,
    }, status.HTTP_200_OK


@app_sub.route("/substance/class/find", methods=["GET"])
@jwt_required()
def find_substance_class():
    term = request.args.get("term", "")
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    try:
        results = substance_service.find_substance_class(term)
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return {
        "status": "success",
        "data": results,
    }, status.HTTP_200_OK


@app_sub.route("/substance/<int:idSubstance>", methods=["PUT"])
@jwt_required()
def setSubstance(idSubstance):
    data = request.get_json()
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    roles = user.config["roles"] if user.config and "roles" in user.config else []
    if "admin" not in roles:
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    subs = Substance.query.get(idSubstance)

    newSubs = False
    if subs is None:
        newSubs = True
        subs = Substance()
        subs.id = idSubstance

    subs.name = data.get("name", None)
    subs.idclass = data.get("idclass", None)
    subs.active = data.get("active", None)

    if newSubs:
        db.session.add(subs)

    return tryCommit(db, escape_html(idSubstance))


@app_sub.route("/substance/<int:idSubstance>/relation", methods=["GET"])
@jwt_required()
def getRelations(idSubstance):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    relations = Relation.findBySctid(idSubstance, user)

    return {"status": "success", "data": relations}, status.HTTP_200_OK


@app_sub.route("/substance/class", methods=["GET"])
@jwt_required()
def get_substance_class():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    classes = SubstanceClass.query.order_by(asc(SubstanceClass.name)).all()

    results = []
    for d in classes:
        results.append(
            {
                "id": d.id,
                "name": d.name.upper(),
            }
        )

    return {"status": "success", "data": results}, status.HTTP_200_OK


@app_sub.route("/relation/<int:sctidA>/<int:sctidB>/<string:kind>", methods=["PUT"])
@jwt_required()
def setRelation(sctidA, sctidB, kind):
    data = request.get_json()
    user = User.find(get_jwt_identity())

    relation = Relation.query.get((sctidA, sctidB, kind))
    if relation is None:
        relation = Relation.query.get((sctidB, sctidA, kind))

    newRelation = False
    if relation is None:
        newRelation = True
        relation = Relation()
        relation.sctida = sctidA
        relation.sctidb = sctidB
        relation.kind = kind
        relation.creator = user.id

    if "text" in data.keys():
        relation.text = data.get("text", None)
    if "active" in data.keys():
        relation.active = bool(data.get("active", False))

    if "level" in data.keys():
        relation.level = data.get("level", None)

    relation.update = datetime.today()
    relation.user = user.id

    if newRelation:
        db.session.add(relation)

    return tryCommit(db, escape_html(sctidA))
