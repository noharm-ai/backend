from flask import Blueprint, request
from markupsafe import escape as escape_html

from services import clinical_notes_service
from decorators.api_endpoint_decorator import api_endpoint

app_note = Blueprint("app_note", __name__)


@app_note.route("/notes/<int:admissionNumber>/v2", methods=["GET"])
@api_endpoint()
def get_notes_v2(admissionNumber):
    return clinical_notes_service.get_notes(
        admission_number=admissionNumber, filter_date=request.args.get("date", None)
    )


@app_note.route("/notes/single/<int:id_clinical_notes>", methods=["GET"])
@api_endpoint()
def get_single_note(id_clinical_notes):
    return clinical_notes_service.get_single_note(id_clinical_notes=id_clinical_notes)


@app_note.route("/notes/<int:idNote>", methods=["POST"])
@api_endpoint()
def changeNote(idNote):
    clinical_notes_service.update_note_text(id=idNote, data=request.get_json())

    return escape_html(idNote)


@app_note.route("/notes", methods=["POST"])
@api_endpoint()
def create():
    data = request.get_json()

    return clinical_notes_service.create_clinical_notes(data=data)


@app_note.route("/notes/remove-annotation", methods=["POST"])
@api_endpoint()
def remove_annotation():
    data = request.get_json()

    clinical_notes_service.remove_annotation(
        id_clinical_notes=data.get("idClinicalNotes", None),
        annotation_type=data.get("annotationType", None),
    )

    return True


@app_note.route("/notes/get-user-last", methods=["GET"])
@api_endpoint()
def get_user_last():
    return clinical_notes_service.get_user_last_clinical_notes(
        admission_number=request.args.get("admissionNumber", None)
    )
