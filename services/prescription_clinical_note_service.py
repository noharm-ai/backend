"""Service: prescription clinical note (prescricao_evolucao) operations."""

from datetime import datetime

from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from models.enums import PrescriptionClinicalNoteStatusEnum
from models.main import User, db
from models.prescription import Prescription, PrescriptionClinicalNote
from models.requests.prescription_clinical_note_request import (
    PrescriptionClinicalNoteUpsertRequest,
)
from services import data_authorization_service
from utils import status


@has_permission(Permission.READ_PRESCRIPTION)
def get_by_prescription(id_prescription: int):
    """Return (PrescriptionClinicalNote, creator_name) tuples for a prescription, ordered by id."""
    creator = db.aliased(User)
    return (
        db.session.query(
            PrescriptionClinicalNote, creator.name.label("created_by_name")
        )
        .outerjoin(creator, PrescriptionClinicalNote.createdBy == creator.id)
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

        if record.tpStatus == PrescriptionClinicalNoteStatusEnum.SENT.value:
            raise ValidationError(
                "Esta evolução não pode ser alterada, pois já foi integrada.",
                "errors.businessRules",
                status.HTTP_400_BAD_REQUEST,
            )
    else:
        record = PrescriptionClinicalNote()
        record.idPrescription = request_data.idPrescription
        record.createdAt = datetime.today()
        record.createdBy = user_context.id

    p = (
        db.session.query(Prescription)
        .filter(Prescription.id == record.idPrescription)
        .first()
    )

    if p is None:
        raise ValidationError(
            "Prescrição inexistente",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    if not data_authorization_service.has_segment_authorization(
        id_segment=p.idSegment, user=user_context
    ):
        raise ValidationError(
            "Usuário não autorizado neste segmento",
            "errors.invalidRegister",
            status.HTTP_401_UNAUTHORIZED,
        )

    record.updatedAt = datetime.today()
    record.updatedBy = user_context.id
    record.idClinicalNoteType = request_data.idClinicalNoteType
    record.concilia = request_data.concilia
    record.tpStatus = PrescriptionClinicalNoteStatusEnum.PENDING.value
    record.errorDescription = request_data.errorDescription
    record.text = request_data.text

    db.session.add(record)
    db.session.flush()

    return record


def to_dto(record: PrescriptionClinicalNote, created_by_name: str = None) -> dict:
    """Convert a PrescriptionClinicalNote model instance to a dict."""
    return {
        "id": record.id,
        "idPrescription": record.idPrescription,
        "notesType": record.idClinicalNoteType,
        "concilia": record.concilia,
        "tpStatus": record.tpStatus,
        "notes": record.text,
        "createdAt": record.createdAt.isoformat() if record.createdAt else None,
        "createdBy": record.createdBy,
        "createdByName": created_by_name,
        "updatedAt": record.updatedAt.isoformat() if record.updatedAt else None,
        "updatedBy": record.updatedBy,
        "sentAt": record.sentAt.isoformat() if record.sentAt else None,
    }
