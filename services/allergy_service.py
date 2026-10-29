"""Service: patient allergy records (alergia)"""

from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from models.main import db
from models.prescription import Prescription
from repository import allergy_repository
from utils import dateutils, status


@has_permission(Permission.MAINTAINER)
def list_allergy_records(id_prescription: int):
    """Every allergy record (alergia) of the prescription's patient, active and
    inactive, for maintainers to check how each one resolves its substance.

    fkmedicamento does not always reference a medicamento record: drug is the
    medicamento with the substance of its sctid when it exists, None
    otherwise, and the record's own name and sctid come next to it"""

    prescription = db.session.get(Prescription, id_prescription)
    if prescription is None:
        raise ValidationError(
            "Registro inexistente", "errors.invalidRecord", status.HTTP_400_BAD_REQUEST
        )

    records = allergy_repository.list_allergy_records(id_patient=prescription.idPatient)

    return [
        {
            "idDrug": _to_str(record.idDrug),
            "drug": (
                {
                    "name": record.drugCatalogName,
                    "sctid": _to_str(record.drugSctid),
                    "substance": record.drugSubstanceName,
                }
                if record.drugId is not None
                else None
            ),
            "drugName": record.drugName,
            "sctid": _to_str(record.sctid),
            "substance": record.substanceName,
            "active": bool(record.active),
            "createdAt": dateutils.to_iso(record.createdAt),
        }
        for record in records
    ]


def _to_str(value):
    """The id as a string (bigints lose precision in javascript), None kept."""
    return str(value) if value is not None else None
