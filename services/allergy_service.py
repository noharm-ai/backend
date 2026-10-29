"""Service: patient allergy records (alergia)"""

from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from models.main import Drug, Substance, User, db
from models.prescription import Prescription
from models.requests.allergy_request import AllergySubstanceRequest
from repository import allergy_repository, culture_drug_repository
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


@has_permission(Permission.MAINTAINER)
def update_allergy_substance(
    request_data: AllergySubstanceRequest, user_context: User = None
):
    """Set the substance of the allergy records of a drug name without a
    medicamento record: every record, of every patient, with the same
    fkmedicamento and nome_medicamento. Without sctid the substance is
    removed. Returns the updated row count.

    The drug name -> sctid mapping (DynamoDB) is updated too. backend-private
    fills alergia.sctid of new records from it and rewrites every record of the
    name created in the last hours that differs, so without it the fix would
    be undone by the next record of the name"""

    # without both, the update would match every record with no drug and no name
    if request_data.idDrug is None and not (
        request_data.drugName and request_data.drugName.strip()
    ):
        raise ValidationError(
            "Informe o medicamento ou o nome do registro",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )

    if (
        request_data.idDrug is not None
        and db.session.get(Drug, request_data.idDrug) is not None
    ):
        raise ValidationError(
            "O registro possui medicamento cadastrado: a substância vem do medicamento",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )

    substance = None
    if request_data.sctid is not None:
        substance = db.session.get(Substance, request_data.sctid)
        if substance is None:
            raise ValidationError(
                "Substância não encontrada",
                "errors.notFound",
                status.HTTP_400_BAD_REQUEST,
            )

    count = allergy_repository.update_sctid(
        id_drug=request_data.idDrug,
        drug_name=request_data.drugName,
        sctid=substance.id if substance else None,
        id_user=user_context.id,
    )
    if count == 0:
        raise ValidationError(
            "Registro inexistente", "errors.invalidRecord", status.HTTP_400_BAD_REQUEST
        )

    # a blank name has no mapping (backend-private skips blank names too)
    if request_data.drugName and request_data.drugName.strip():
        # after the update: a failure here rolls it back
        culture_drug_repository.put_sctid(
            name=request_data.drugName,
            sctid=substance.id if substance else None,
            idclass=substance.idclass if substance else None,
        )

    return {"updated": count}


def _to_str(value):
    """The id as a string (bigints lose precision in javascript), None kept."""
    return str(value) if value is not None else None
