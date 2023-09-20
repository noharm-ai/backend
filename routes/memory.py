from models.main import *
from models.appendix import *
from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from .utils import tryCommit

from services import memory_service
from exception.validation_error import ValidationError

app_mem = Blueprint("app_mem", __name__)


@app_mem.route("/memory/<string:kind>", methods=["GET"])
@jwt_required()
def getMemory(kind):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    if memory_service.is_admin_memory(kind):
        return {
            "status": "error",
            "message": "Registro inválido",
            "code": "errors.invalidRecord",
        }, status.HTTP_400_BAD_REQUEST

    memList = Memory.query.filter(Memory.kind == kind).all()

    results = []
    for m in memList:
        results.append({"key": m.key, "value": m.value})

    return {"status": "success", "data": results}, status.HTTP_200_OK


@app_mem.route("/memory/", methods=["PUT"])
@app_mem.route("/memory", methods=["PUT"])
@app_mem.route("/memory/<int:idMemory>", methods=["PUT"])
@jwt_required()
def save_memory(idMemory=None):
    data = request.get_json()
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    try:
        mem = memory_service.save_memory(
            idMemory, data.get("type"), data.get("value"), user
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, mem.key)


@app_mem.route("/memory/unique/<string:kind>", methods=["PUT"])
@jwt_required()
def save_memory_unique(kind):
    data = request.get_json()
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    try:
        mem = memory_service.save_unique_memory(kind, data.get("value"), user)
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, mem.key)
