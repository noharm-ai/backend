"""Service: recent cultures of an admission

The culture card of the screening reads the antibiograms by drug, which does
not tell which culture exams were made nor what they found. The infection
control page shows them apart: the latest culture of each exam and material,
with its gram and the lab's result, released in the last days. It is only
informative, so it is served apart from the antimicrobial timeline and a
failure here never takes the page down.

The cultures are the patient's, not only the admission's: a culture from a
recent earlier admission still matters to the treatment now.
"""

from datetime import datetime, timedelta

from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from repository import culture_repository, patient_repository
from repository.infection_control import antimicrobial_repository
from services import culture_service
from utils import dateutils, status

# a culture released before this is old news for the treatment now
FRESHNESS = timedelta(days=60)
# the history of one exam and material is a few dozen cultures at most: this
# only bounds a runaway integration
HISTORY_LIMIT = 200


def _get_id_patient(admission_number: int) -> int:
    """The patient of the admission, from its latest prescription when the
    admission has no patient record (as the antimicrobial timeline does)"""
    patient = patient_repository.get_patient_by_admission(
        admission_number=admission_number
    )
    if patient is not None:
        return patient.idPatient

    last_prescription = antimicrobial_repository.get_last_prescription(
        admission_number=admission_number
    )
    if last_prescription is not None:
        return last_prescription[0].idPatient

    raise ValidationError(
        "Registro inválido",
        "errors.invalidRecord",
        status.HTTP_400_BAD_REQUEST,
    )


def _text(value):
    """A blank field says nothing, same as a missing one"""
    if value is None or f"{value}".strip() == "":
        return None

    return f"{value}".strip()


def _serialize_antibiogram(rows: list) -> list[dict]:
    """The released results of a culture, read as the culture card reads them
    (culture_service): resistant, susceptible or a wording it could not
    classify, which is never shown as either"""
    antibiogram = []

    for row in rows:
        result = row.result.strip()
        result_type = culture_service.classify_result(result)

        antibiogram.append(
            {
                "microorganism": _text(row.microorganism),
                "drug": row.drug.strip(),
                "result": result,
                "resultType": result_type.value,
                "resultDetail": culture_service.result_detail(result, result_type),
                "mic": culture_service.format_mic(row.microorganismAmount),
            }
        )

    return antibiogram


def _serialize(headers: list, with_antibiogram: bool = False) -> list[dict]:
    """The cultures with the microorganisms their antibiograms name, and with
    the antibiogram itself when asked (the history, opened on one culture)"""
    id_exam_items = [h.idExamItem for h in headers if h.idExamItem is not None]
    microorganisms = culture_repository.get_microorganisms(id_exam_items=id_exam_items)
    antibiograms = (
        culture_repository.get_antibiograms(id_exam_items=id_exam_items)
        if with_antibiogram
        else {}
    )

    cultures = []
    for header in headers:
        culture = {
            "id": str(header.id),
            "examName": _text(header.examName),
            "material": _text(header.examMaterialName),
            "collectionDate": dateutils.to_iso(header.collectionDate),
            "releaseDate": dateutils.to_iso(header.releaseDate),
            "gram": _text(header.gram),
            "previousResult": _text(header.previousResult),
            "microorganisms": microorganisms.get(header.idExamItem, []),
        }

        if with_antibiogram:
            culture["antibiogram"] = _serialize_antibiogram(
                antibiograms.get(header.idExamItem, [])
            )

        cultures.append(culture)

    return cultures


def _sort_key(culture: dict):
    # the dates share one format (dateutils.to_iso), so the text order is the
    # chronological order
    return (culture["collectionDate"] or "", culture["releaseDate"] or "")


@has_permission(Permission.READ_PRESCRIPTION)
def get_recent_cultures(admission_number: int):
    """The latest culture of each exam and material of the patient released in
    the last FRESHNESS, newest collection first.

    The result (previousResult) goes as the lab wrote it: some send HTML, some
    plain text, and the page sanitizes it before showing it.
    """
    id_patient = _get_id_patient(admission_number=admission_number)
    released_since = datetime.now() - FRESHNESS

    headers = culture_repository.get_latest_culture_headers(
        id_patient=id_patient, released_since=released_since
    )
    cultures = _serialize(headers)

    return {
        "admissionNumber": admission_number,
        "releasedSince": dateutils.to_iso(released_since),
        "cultures": sorted(cultures, key=_sort_key, reverse=True),
    }


@has_permission(Permission.READ_PRESCRIPTION)
def get_culture_history(admission_number: int, id_culture: int):
    """Every culture of the patient with the exam and material of the given
    one, newest collection first, released at any time, each with its
    antibiogram: what a row of the recent cultures opens. The antibiogram of
    the clicked culture comes first on the screen, and its previous
    collections are one click away, without another request.

    The culture must be the patient's, so that the admission on screen never
    opens another patient's history.
    """
    id_patient = _get_id_patient(admission_number=admission_number)
    culture = culture_repository.get_culture_header(
        id_culture=id_culture, id_patient=id_patient
    )

    if culture is None:
        raise ValidationError(
            "Registro inválido",
            "errors.invalidRecord",
            status.HTTP_400_BAD_REQUEST,
        )

    headers = culture_repository.get_culture_headers_of_exam(
        id_patient=id_patient,
        exam_name=culture.examName,
        material=culture.examMaterialName,
        limit=HISTORY_LIMIT,
    )

    return {
        "admissionNumber": admission_number,
        "examName": _text(culture.examName),
        "material": _text(culture.examMaterialName),
        "cultures": _serialize(headers, with_antibiogram=True),
    }
