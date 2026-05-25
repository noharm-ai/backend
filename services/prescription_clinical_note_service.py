"""Service: prescription clinical note (prescricao_evolucao) operations."""

from datetime import datetime

from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from models.main import User, db
from models.prescription import PrescriptionClinicalNote
from models.requests.prescription_clinical_note_request import (
    PrescriptionClinicalNoteUpsertRequest,
)
from utils import status


@has_permission(Permission.READ_PRESCRIPTION)
def get_by_prescription(id_prescription: int):
    """Return all clinical note records for the given prescription, ordered by id."""
    return (
        db.session.query(PrescriptionClinicalNote)
        .filter(PrescriptionClinicalNote.idPrescription == id_prescription)
        .order_by(PrescriptionClinicalNote.id)
        .all()
    )


@has_permission(Permission.WRITE_PRESCRIPTION)
def upsert(
    request_data: PrescriptionClinicalNoteUpsertRequest,
    user_context: User = None,
):
    """Create or update a prescription clinical note record.

    If request_data.id is provided, the existing record is updated.
    Otherwise a new record is created with created_at/created_by set to now/current user.
    """
    if request_data.id is not None:
        record = (
            db.session.query(PrescriptionClinicalNote)
            .filter(PrescriptionClinicalNote.id == request_data.id)
            .first()
        )
        if record is None:
            raise ValidationError(
                "Registro inexistente",
                "errors.invalidRecord",
                status.HTTP_400_BAD_REQUEST,
            )
    else:
        record = PrescriptionClinicalNote()
        record.idPrescription = request_data.idPrescription
        record.createdAt = datetime.today()
        record.createdBy = user_context.id

    record.updatedAt = datetime.today()
    record.updatedBy = user_context.id
    record.idTipoEvolucao = request_data.idTipoEvolucao
    record.concilia = request_data.concilia
    record.tpStatus = request_data.tpStatus
    record.descErroIntegracao = request_data.descErroIntegracao
    record.texto = request_data.texto

    db.session.add(record)
    db.session.flush()

    return record


def to_dto(record: PrescriptionClinicalNote) -> dict:
    """Convert a PrescriptionClinicalNote model instance to a dict."""
    return {
        "id": record.id,
        "idPrescription": record.idPrescription,
        "idTipoEvolucao": record.idTipoEvolucao,
        "concilia": record.concilia,
        "tpStatus": record.tpStatus,
        "descErroIntegracao": record.descErroIntegracao,
        "texto": record.texto,
        "createdAt": record.createdAt.isoformat() if record.createdAt else None,
        "createdBy": record.createdBy,
        "updatedAt": record.updatedAt.isoformat() if record.updatedAt else None,
        "updatedBy": record.updatedBy,
    }
