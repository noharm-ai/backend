import os
from flask_api import status
from models.main import *
from flask import Blueprint, request, escape
from flask_jwt_extended import jwt_required, get_jwt_identity

from .utils import *
from services import drug_service
from exception.validation_error import ValidationError

app_drugs = Blueprint("app_drugs", __name__)


@app_drugs.route(
    "/drugs/resources/<int:idDrug>/<int:idSegment>/<int:idHospital>", methods=["GET"]
)
@jwt_required()
def getDrugSummary(idDrug, idSegment, idHospital):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    drug = Drug.query.get(idDrug)

    prescribedUnits = drug_service.getPreviouslyPrescribedUnits(idDrug, idSegment)
    allUnits = drug_service.getUnits(idHospital)

    unitResults = []
    for u in prescribedUnits:
        unitResults.append(
            {"id": u.id, "description": u.description, "amount": u.count}
        )
    for u in allUnits:
        unitResults.append({"id": u.id, "description": u.description, "amount": 0})

    prescribedFrequencies = drug_service.getPreviouslyPrescribedFrequencies(
        idDrug, idSegment
    )
    allFrequencies = drug_service.getFrequencies(idHospital)

    frequencyResults = []
    for f in prescribedFrequencies:
        frequencyResults.append(
            {"id": f.id, "description": f.description, "amount": f.count}
        )
    for f in allFrequencies:
        frequencyResults.append({"id": f.id, "description": f.description, "amount": 0})

    results = {
        "drug": {"id": int(idDrug), "name": drug.name if drug else ""},
        "units": unitResults,
        "frequencies": frequencyResults,
    }

    return {"status": "success", "data": results}, status.HTTP_200_OK


@app_drugs.route("/drugs/frequencies", methods=["GET"])
@jwt_required()
def get_frequencies():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    all_frequencies = drug_service.get_all_frequencies()

    results = []
    for f in all_frequencies:
        results.append(
            {
                "id": f[0],
                "description": f[1],
            }
        )

    return {"status": "success", "data": results}, status.HTTP_200_OK


@app_drugs.route("/drugs/attributes/<int:id_segment>/<int:id_drug>", methods=["GET"])
@jwt_required()
def get_drug_attributes(id_segment, id_drug):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    try:
        result = drug_service.get_attributes(
            id_segment=id_segment, id_drug=id_drug, user=user
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return {
        "status": "success",
        "data": result,
    }, status.HTTP_200_OK


@app_drugs.route("/drugs/attributes", methods=["POST"])
@jwt_required()
def save_drug_attributes():
    data = request.get_json()
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    try:
        drug_service.save_attributes(
            id_drug=data.get("idDrug", None),
            id_segment=data.get("idSegment", None),
            data=data,
            user=user,
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, True)


@app_drugs.route("/drugs/substance", methods=["POST"])
@jwt_required()
def update_substance():
    data = request.get_json()
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ["TZ"] = "America/Sao_Paulo"

    id_drug = data.get("idDrug", None)
    sctid = data.get("sctid", None)

    try:
        drug_service.update_substance(
            id_drug=id_drug,
            sctid=sctid,
            user=user,
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, {"idDrug": escape(id_drug), "sctid": escape(str(sctid))})
