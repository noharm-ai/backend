import os

from models.main import *
from models.appendix import *
from models.segment import *
from models.prescription import *
from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from .utils import *

from services.prescription_drug_edit_service import (
    createPrescriptionDrug,
    updatePrescriptionDrug,
    togglePrescriptionDrugSuspension,
    get_missing_drugs,
    copy_missing_drugs,
)
from services.prescription_drug_service import (
    getPrescriptionDrug,
    prescriptionDrugToDTO,
)
from exception.validation_error import ValidationError

app_pres_crud = Blueprint("app_pres_crud", __name__)


@app_pres_crud.route("/editPrescription/drug/<int:idPrescriptionDrug>", methods=["PUT"])
@jwt_required()
def actionUpdatePrescriptionDrug(idPrescriptionDrug):
    data = request.get_json()
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ["TZ"] = "America/Sao_Paulo"

    try:
        updatePrescriptionDrug(idPrescriptionDrug, data, user)
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    pd = getPrescriptionDrug(idPrescriptionDrug)

    return tryCommit(db, prescriptionDrugToDTO(pd), user.permission())


@app_pres_crud.route("/editPrescription/drug", methods=["POST"])
@jwt_required()
def actionCreatePrescriptionDrug():
    data = request.get_json()
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ["TZ"] = "America/Sao_Paulo"

    try:
        newId = createPrescriptionDrug(data, user)
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    pd = getPrescriptionDrug(newId)

    return tryCommit(db, prescriptionDrugToDTO(pd), user.permission())


@app_pres_crud.route(
    "/editPrescription/drug/<int:idPrescriptionDrug>/suspend/<int:suspend>",
    methods=["PUT"],
)
@jwt_required()
def actionSuspendPrescriptionDrug(idPrescriptionDrug, suspend):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ["TZ"] = "America/Sao_Paulo"

    try:
        pdUpdate = togglePrescriptionDrugSuspension(
            idPrescriptionDrug, user, True if suspend == 1 else False
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    result = {
        "idPrescription": str(pdUpdate.idPrescription),
        "idPrescriptionDrug": str(pdUpdate.id),
        "idDrug": pdUpdate.idDrug,
        "suspended": True if suspend == 1 else False,
    }

    return tryCommit(db, result, user.permission())


@app_pres_crud.route(
    "/editPrescription/<int:idPrescription>/missing-drugs", methods=["GET"]
)
@jwt_required()
def get_prescription_missing_drugs(idPrescription):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ["TZ"] = "America/Sao_Paulo"

    try:
        missing_drugs = get_missing_drugs(idPrescription, user)
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    list = []

    for d in missing_drugs:
        list.append({"idDrug": d[0], "name": d[1]})

    return {"status": "success", "data": list}, status.HTTP_200_OK


@app_pres_crud.route(
    "/editPrescription/<int:idPrescription>/missing-drugs/copy", methods=["POST"]
)
@jwt_required()
def copy_prescription_missing_drugs(idPrescription):
    data = request.get_json()
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ["TZ"] = "America/Sao_Paulo"

    try:
        ids = copy_missing_drugs(idPrescription, user, data.get("idDrugs", None))
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, 1, user.permission())
