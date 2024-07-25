import os
from flask import Blueprint, request
from markupsafe import escape as escape_html
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime

from models.main import db, dbSession, User
from models.notes import ClinicalNotes
from services import clinical_notes_service, memory_service
from .utils import tryCommit
from utils import status
from exception.validation_error import ValidationError

app_note = Blueprint("app_note", __name__)


@app_note.route("/notes/<int:admissionNumber>/v2", methods=["GET"])
@jwt_required()
def get_notes_v2(admissionNumber):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    try:
        result = clinical_notes_service.get_notes(
            admission_number=admissionNumber, filter_date=request.args.get("date", None)
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return {"status": "success", "data": result}, status.HTTP_200_OK


@app_note.route("/notes/single/<int:id_clinical_notes>", methods=["GET"])
@jwt_required()
def get_single_note(id_clinical_notes):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    try:
        result = clinical_notes_service.get_single_note(
            id_clinical_notes=id_clinical_notes
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return {"status": "success", "data": result}, status.HTTP_200_OK


@app_note.route("/notes/<int:idNote>", methods=["POST"])
@jwt_required()
def changeNote(idNote):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    has_primary_care = memory_service.has_feature("PRIMARYCARE")
    data = request.get_json()

    if not ClinicalNotes.exists():
        return {
            "status": "error",
            "message": "Schema não tem evolução!",
        }, status.HTTP_400_BAD_REQUEST

    n = ClinicalNotes.query.get(idNote)

    if n is None:
        return {
            "status": "error",
            "message": "Evolução Inexistente!",
        }, status.HTTP_400_BAD_REQUEST

    n.update = datetime.today()
    n.user = user.id

    if "text" in data.keys():
        n.text = data.get("text", None)
        n.medications = n.text.count("annotation-medicamentos")
        n.complication = n.text.count("annotation-complicacoes")
        n.symptoms = n.text.count("annotation-sintomas")
        n.diseases = n.text.count("annotation-doencas")
        n.info = n.text.count("annotation-dados")
        n.conduct = n.text.count("annotation-conduta")
        n.signs = n.text.count("annotation-sinais")
        n.allergy = n.text.count("annotation-alergia")
        n.names = n.text.count("annotation-nomes")

    if has_primary_care:
        if "date" in data.keys() and data.get("date", None) != None:
            n.date = data.get("date")

        if "form" in data.keys() and data.get("form", None) != None:
            n.form = data.get("form")

    return tryCommit(db, escape_html(idNote))


@app_note.route("/notes", methods=["POST"])
@jwt_required()
def create():
    data = request.get_json()
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ["TZ"] = "America/Sao_Paulo"

    try:
        id = clinical_notes_service.create_clinical_notes(data, user)
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, id, user.permission())


@app_note.route("/notes/remove-annotation", methods=["POST"])
@jwt_required()
def remove_annotation():
    data = request.get_json()
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ["TZ"] = "America/Sao_Paulo"

    try:
        clinical_notes_service.remove_annotation(
            id_clinical_notes=data.get("idClinicalNotes", None),
            annotation_type=data.get("annotationType", None),
            user=user,
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, True, user.permission())
