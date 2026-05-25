from flask import Blueprint, request

from decorators.api_endpoint_decorator import api_endpoint
from models.requests.prescription_clinical_note_request import (
    PrescriptionClinicalNoteUpsertRequest,
)
from services import prescription_clinical_note_service

app_pres_clinical_note = Blueprint("app_pres_clinical_note", __name__)


@app_pres_clinical_note.route(
    "/prescription-clinical-note/<int:id_prescription>", methods=["GET"]
)
@api_endpoint()
def list_records(id_prescription: int):
    """List clinical note records for a prescription."""
    records = prescription_clinical_note_service.get_by_prescription(id_prescription)

    return [prescription_clinical_note_service.to_dto(r) for r in records]


@app_pres_clinical_note.route("/prescription-clinical-note", methods=["POST"])
@api_endpoint()
def upsert_record():
    """Create or update a prescription clinical note record."""
    record = prescription_clinical_note_service.upsert(
        request_data=PrescriptionClinicalNoteUpsertRequest(**request.get_json())
    )

    return prescription_clinical_note_service.to_dto(record)
