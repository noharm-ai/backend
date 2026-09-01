"""Service: origin system integration status of a prescription"""

from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from models.main import db
from models.prescription import Prescription
from repository import prescription_view_repository
from utils import dateutils, status

# keys used by the origin system integration to describe why the release failed
_INTEGRATION_ERROR_MESSAGE_KEYS = (
    "message",
    "error",
    "erro",
    "descricao",
    "description",
)


@has_permission(Permission.READ_PRESCRIPTION)
def route_get_integration_errors(id_prescription: int, id_prescription_list: list[int]):
    """
    List the release integration errors that are still pending for this prescription.

    The release message is only sent to the origin system after a check, so an
    unchecked prescription can never have a pending error.

    Aggregated prescriptions are released one internal prescription at a time.
    Rebuilding that list here would repeat the query the view endpoint already
    ran, so the caller sends the ids it has on screen in ``id_prescription_list``
    and the repository restricts them to the admission of this prescription.
    """

    prescription = (
        db.session.query(Prescription)
        .filter(Prescription.id == id_prescription)
        .first()
    )

    if prescription is None:
        raise ValidationError(
            "Prescrição inexistente",
            "errors.invalidRecord",
            status.HTTP_400_BAD_REQUEST,
        )

    if prescription.status != "s":
        return []

    id_prescriptions = list({prescription.id, *(id_prescription_list or [])})

    errors = prescription_view_repository.get_pending_integration_errors(
        id_prescriptions=id_prescriptions,
        admission_number=prescription.admissionNumber,
    )

    return [
        {
            "idPrescription": str(error.id_prescription),
            "date": dateutils.to_iso(error.created_at),
            "message": _get_integration_error_message(error.extra),
            "extra": error.extra,
        }
        for error in errors
    ]


def _get_integration_error_message(extra):
    """Extract a readable message from the audit ``extra`` payload, if there is one."""

    if not isinstance(extra, dict):
        return None

    for key in _INTEGRATION_ERROR_MESSAGE_KEYS:
        value = extra.get(key)
        if value:
            return str(value)

    return None
