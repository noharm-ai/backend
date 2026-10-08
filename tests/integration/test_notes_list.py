"""Tests: GET /notes/<admissionNumber>/v2 — the clinical-note timeline.

This is what the patient screen calls to build the notes timeline of an
admission. The endpoint answers three things at once, and each has its own
rules:

* ``dates`` — one entry per calendar day that carries notes, newest first,
  with how many notes that day holds, which positions (``cargo``) wrote them
  and the per-tag annotation counts the text mining left behind;
* ``notes`` — the notes themselves, but only for the **three most recent
  days**, merged from two different tables: the notes the hospital sends
  (``demo.evolucao``) and the ones written inside NoHarm
  (``demo.prescricao_evolucao``);
* ``previousAdmissions`` — the other admissions of the same patient, so the
  screen can offer to jump to them.

Passing ``?date=`` switches the endpoint to a single day: ``dates`` and
``previousAdmissions`` are then not computed at all.

What these tests pin down:

* exam rows (``evolucao.exame``) are not notes and are counted nowhere;
* a day's ``count`` adds up both sources while its ``roles`` only names the
  positions found on the hospital notes, and a day that exists *only* because
  of a NoHarm note is still listed, tagged "EVOLUÇÃO CRIADA NA NOHARM";
* the three-day window limits the notes but not the date list, so a day older
  than the window is listed with its count and no note body;
* the merged list is ordered newest first and each source keeps its own shape
  (a NoHarm note carries ``source``, ``idPrescription`` and its integration
  status; a hospital note carries the signature id);
* annotation counts reach the note under both the internal name and the
  legacy column alias, while a date entry carries only the alias;
* the date filter narrows the notes and empties the rest of the answer;
* an admission nobody wrote about answers empty rather than failing;
* READ_REGULATION is enough to read the timeline, and a caller holding
  neither it nor READ_PRESCRIPTION is refused.
"""

from datetime import datetime

import pytest
from sqlalchemy import text

from tests.conftest import session, session_commit
from tests.utils.utils_test_prescription import test_counters
from utils import status

# the four days the hospital wrote on, newest first, plus one day that only
# exists because a NoHarm note was written on it
DAY_NOHARM_ONLY = datetime(2024, 3, 15, 8, 30)
DAY_1 = datetime(2024, 3, 14, 10, 0)
DAY_2 = datetime(2024, 3, 13, 9, 0)
DAY_3 = datetime(2024, 3, 12, 11, 0)
DAY_4 = datetime(2024, 3, 11, 7, 0)

# get_notes loads the notes of the three most recent days only
NOTES_WINDOW = 3

# name of the user behind created_by = 1 (public.usuario)
CREATOR_NAME = "Demonstração"

NOHARM_POSITION = "EVOLUÇÃO CRIADA NA NOHARM"

PHARMACIST = "Farmacêutica"
PHYSICIAN = "Médico"

# admissions this module writes to, cleaned up by admission number
_admissions = []

# ids handed out to the evolucao rows written here; kept clear of the ranges
# the other notes modules reserve
_next_note_id = 200000


def _url(admission: int, date: str = None) -> str:
    """The timeline endpoint of an admission, optionally for a single day."""
    url = f"/notes/{admission}/v2"

    return f"{url}?date={date}" if date else url


def _next_admission() -> int:
    """Reserve an admission number no other test uses."""
    admission = test_counters["admission_number"]
    test_counters["admission_number"] += 1
    _admissions.append(admission)

    return admission


def _insert_note(
    admission: int,
    date: datetime,
    position: str = PHARMACIST,
    is_exam: bool = False,
    annotations: str = None,
    id_sign_request: int = None,
    text_content: str = "Evolução de teste",
) -> int:
    """Write a demo.evolucao row — a note the hospital sent us."""
    global _next_note_id
    id_note = _next_note_id
    _next_note_id += 1

    session.execute(
        text(
            "INSERT INTO demo.evolucao "
            "(fkevolucao, nratendimento, texto, dtevolucao, prescritor, cargo, "
            "exame, anotacoes, fkassinatura) "
            "VALUES (:id, :admission, :text, :date, :prescriber, :position, "
            ":is_exam, CAST(:annotations AS jsonb), :id_sign_request)"
        ),
        {
            "id": id_note,
            "admission": admission,
            "text": text_content,
            "date": date,
            "prescriber": "Fulano Beltrano",
            "position": position,
            "is_exam": is_exam,
            "annotations": annotations,
            "id_sign_request": id_sign_request,
        },
    )

    return id_note


def _insert_noharm_note(
    admission: int,
    updated_at: datetime,
    id_prescription: int,
    tp_status: int = 0,
    text_content: str = "Evolução escrita na NoHarm",
) -> int:
    """Write a demo.prescricao_evolucao row — a note written inside NoHarm."""
    result = session.execute(
        text(
            "INSERT INTO demo.prescricao_evolucao "
            "(fkprescricao, nratendimento, texto, tp_status, "
            "created_at, created_by, updated_at) "
            "VALUES (:id_prescription, :admission, :text, :tp_status, "
            ":updated_at, 1, :updated_at) "
            "RETURNING idprescricao_evolucao"
        ),
        {
            "id_prescription": id_prescription,
            "admission": admission,
            "text": text_content,
            "tp_status": tp_status,
            "updated_at": updated_at,
        },
    )

    return result.first()[0]


def _insert_admission(
    admission: int, id_patient: int, admitted: datetime, discharged=None
):
    """Write a demo.pessoa row so the admission belongs to a patient."""
    session.execute(
        text(
            "INSERT INTO demo.pessoa "
            "(fkhospital, fkpessoa, nratendimento, dtnascimento, dtinternacao, dtalta) "
            "VALUES (1, :id_patient, :admission, :birthdate, :admitted, :discharged)"
        ),
        {
            "id_patient": id_patient,
            "admission": admission,
            "birthdate": datetime(1980, 1, 1),
            "admitted": admitted,
            "discharged": discharged,
        },
    )


def _cleanup():
    """Drop every row this module wrote — tests.conftest does not know them."""
    if not _admissions:
        return

    for table in ("demo.evolucao", "demo.prescricao_evolucao"):
        session.execute(
            text(f"DELETE FROM {table} WHERE nratendimento = ANY(:admissions)"),
            {"admissions": _admissions},
        )

    session.execute(
        text("DELETE FROM demo.pessoa WHERE nratendimento = ANY(:admissions)"),
        {"admissions": _admissions},
    )
    session_commit()


def _by_date(response_json: dict) -> dict:
    """Index the date entries of a timeline answer by their ISO date."""
    return {entry["date"]: entry for entry in response_json["dates"]}


def _by_id(response_json: dict) -> dict:
    """Index the notes of a timeline answer by their id."""
    return {note["id"]: note for note in response_json["notes"]}


class Timeline:
    """The ids written by the ``timeline`` fixture, for the assertions."""

    def __init__(self, admission):
        self.admission = admission
        self.day1_annotated = None
        self.day1_physician = None
        self.day1_exam = None
        self.day2_note = None
        self.day2_noharm = None
        self.day3_note = None
        self.day4_note = None
        self.noharm_only = None
        self.id_prescription = None


@pytest.fixture(scope="module")
def timeline():
    """An admission written about on five days, by both note sources.

    Read-only for every test that uses it, so it is built once:

    * 2024-03-15 — a NoHarm note and nothing else;
    * 2024-03-14 — two hospital notes (one annotated, one by another
      position) and an exam row that must stay out of the answer;
    * 2024-03-13 — one hospital note and one NoHarm note;
    * 2024-03-12 and 2024-03-11 — one hospital note each, both older than the
      three-day notes window.
    """
    _cleanup()

    data = Timeline(_next_admission())
    admission = data.admission

    data.id_prescription = test_counters["id_prescription"]
    test_counters["id_prescription"] += 1

    data.noharm_only = _insert_noharm_note(
        admission=admission,
        updated_at=DAY_NOHARM_ONLY,
        id_prescription=data.id_prescription,
        tp_status=1,
    )

    data.day1_annotated = _insert_note(
        admission=admission,
        date=DAY_1,
        annotations='{"alergia_count": 2, "conduta_count": 1}',
        id_sign_request=4242,
    )
    data.day1_physician = _insert_note(
        admission=admission, date=DAY_1, position=PHYSICIAN
    )
    data.day1_exam = _insert_note(admission=admission, date=DAY_1, is_exam=True)

    data.day2_note = _insert_note(admission=admission, date=DAY_2)
    data.day2_noharm = _insert_noharm_note(
        admission=admission,
        updated_at=DAY_2,
        id_prescription=data.id_prescription,
    )

    data.day3_note = _insert_note(admission=admission, date=DAY_3)
    data.day4_note = _insert_note(admission=admission, date=DAY_4)

    session_commit()

    yield data

    _cleanup()


#
# dates
#


def test_dates_list_every_day_newest_first(client, analyst_headers, timeline):
    """Every day carrying a note is listed, ordered from the newest down."""
    response = client.get(_url(timeline.admission), headers=analyst_headers)

    assert response.status_code == status.HTTP_200_OK
    dates = [entry["date"] for entry in response.get_json()["data"]["dates"]]
    assert dates == [
        DAY_NOHARM_ONLY.date().isoformat(),
        DAY_1.date().isoformat(),
        DAY_2.date().isoformat(),
        DAY_3.date().isoformat(),
        DAY_4.date().isoformat(),
    ]


def test_dates_ignore_exam_rows(client, analyst_headers, timeline):
    """An exam row shares the table with the notes but is never counted."""
    response = client.get(_url(timeline.admission), headers=analyst_headers)

    entry = _by_date(response.get_json()["data"])[DAY_1.date().isoformat()]
    assert entry["count"] == 2


def test_dates_count_both_note_sources(client, analyst_headers, timeline):
    """A day's count adds the NoHarm notes to the hospital ones."""
    response = client.get(_url(timeline.admission), headers=analyst_headers)

    entry = _by_date(response.get_json()["data"])[DAY_2.date().isoformat()]
    assert entry["count"] == 2
    assert entry["roles"] == [PHARMACIST]


def test_dates_report_every_position_of_the_day(client, analyst_headers, timeline):
    """The roles of a day name each distinct position that wrote on it."""
    response = client.get(_url(timeline.admission), headers=analyst_headers)

    entry = _by_date(response.get_json()["data"])[DAY_1.date().isoformat()]
    assert set(entry["roles"]) == {PHARMACIST, PHYSICIAN}


def test_dates_include_days_only_noharm_wrote_on(client, analyst_headers, timeline):
    """A day the hospital never wrote on is still listed, under its own role."""
    response = client.get(_url(timeline.admission), headers=analyst_headers)

    entry = _by_date(response.get_json()["data"])[DAY_NOHARM_ONLY.date().isoformat()]
    assert entry["count"] == 1
    assert entry["roles"] == [NOHARM_POSITION]


def test_dates_sum_annotation_counts_under_the_column_alias(
    client, analyst_headers, timeline
):
    """A date entry carries the annotation totals under the legacy alias only."""
    response = client.get(_url(timeline.admission), headers=analyst_headers)

    entry = _by_date(response.get_json()["data"])[DAY_1.date().isoformat()]
    assert entry["allergy"] == 2
    assert entry["conduct"] == 1
    assert "alergia" not in entry
    # a tag without a legacy column keeps its own name
    assert entry["germes"] == 0


def test_noharm_only_date_zeroes_both_annotation_keys(
    client, analyst_headers, timeline
):
    """A day carried by NoHarm notes alone reports zero under name and alias."""
    response = client.get(_url(timeline.admission), headers=analyst_headers)

    entry = _by_date(response.get_json()["data"])[DAY_NOHARM_ONLY.date().isoformat()]
    assert entry["allergy"] == 0
    assert entry["alergia"] == 0


#
# notes
#


def test_notes_are_limited_to_the_three_most_recent_days(
    client, analyst_headers, timeline
):
    """Notes older than the three-day window are left out of the note list."""
    response = client.get(_url(timeline.admission), headers=analyst_headers)

    data = response.get_json()["data"]
    assert len(data["dates"]) > NOTES_WINDOW

    ids = set(_by_id(data))
    assert ids == {
        str(timeline.noharm_only),
        str(timeline.day1_annotated),
        str(timeline.day1_physician),
        str(timeline.day2_note),
        str(timeline.day2_noharm),
    }
    assert str(timeline.day3_note) not in ids
    assert str(timeline.day4_note) not in ids


def test_notes_never_include_exam_rows(client, analyst_headers, timeline):
    """The exam row of a listed day is not served as a note either."""
    response = client.get(_url(timeline.admission), headers=analyst_headers)

    assert str(timeline.day1_exam) not in _by_id(response.get_json()["data"])


def test_notes_are_ordered_newest_first(client, analyst_headers, timeline):
    """The merged list is sorted by date, whichever table a note comes from."""
    response = client.get(_url(timeline.admission), headers=analyst_headers)

    dates = [note["date"] for note in response.get_json()["data"]["notes"]]
    assert dates == sorted(dates, reverse=True)
    assert dates[0] == DAY_NOHARM_ONLY.isoformat()


def test_hospital_note_shape(client, analyst_headers, timeline):
    """A hospital note keeps its prescriber, position and signature id."""
    response = client.get(_url(timeline.admission), headers=analyst_headers)

    note = _by_id(response.get_json()["data"])[str(timeline.day1_annotated)]
    assert note["admissionNumber"] == timeline.admission
    assert note["text"] == "Evolução de teste"
    assert note["date"] == DAY_1.isoformat()
    assert note["prescriber"] == "Fulano Beltrano"
    assert note["position"] == PHARMACIST
    assert note["idSignRequest"] == 4242
    # PRIMARYCARE is off on the demo schema, so the form is not served
    assert note["form"] is None
    assert note["template"] is None
    assert "source" not in note


def test_noharm_note_shape(client, analyst_headers, timeline):
    """A NoHarm note names its source, prescription and integration status."""
    response = client.get(_url(timeline.admission), headers=analyst_headers)

    note = _by_id(response.get_json()["data"])[str(timeline.noharm_only)]
    assert note["source"] == "prescription"
    assert note["position"] == NOHARM_POSITION
    assert note["prescriber"] == CREATOR_NAME
    assert note["idPrescription"] == timeline.id_prescription
    assert note["integrationStatus"] == 1
    assert note["date"] == DAY_NOHARM_ONLY.isoformat()
    # rows of prescricao_evolucao cannot be signed
    assert note["idSignRequest"] is None


def test_note_annotation_counts_use_name_and_alias(client, analyst_headers, timeline):
    """An annotated note reports its counts under both keys."""
    response = client.get(_url(timeline.admission), headers=analyst_headers)

    note = _by_id(response.get_json()["data"])[str(timeline.day1_annotated)]
    assert note["alergia"] == 2
    assert note["allergy"] == 2
    assert note["conduta"] == 1
    assert note["conduct"] == 1


def test_note_without_annotations_reports_zero(client, analyst_headers, timeline):
    """A note the text mining left untouched reports zero for every tag."""
    response = client.get(_url(timeline.admission), headers=analyst_headers)

    note = _by_id(response.get_json()["data"])[str(timeline.day1_physician)]
    assert note["alergia"] == 0
    assert note["allergy"] == 0


def test_noharm_note_reports_zero_annotations(client, analyst_headers, timeline):
    """NoHarm notes are never mined, so every tag comes back zero."""
    response = client.get(_url(timeline.admission), headers=analyst_headers)

    note = _by_id(response.get_json()["data"])[str(timeline.noharm_only)]
    assert note["alergia"] == 0
    assert note["allergy"] == 0


#
# ?date= — a single day
#


def test_date_filter_serves_that_day_only(client, analyst_headers, timeline):
    """A filtered call serves the notes of the requested day, window or not."""
    response = client.get(
        _url(timeline.admission, date=DAY_3.date().isoformat()),
        headers=analyst_headers,
    )

    assert response.status_code == status.HTTP_200_OK
    assert set(_by_id(response.get_json()["data"])) == {str(timeline.day3_note)}


def test_date_filter_merges_both_sources(client, analyst_headers, timeline):
    """The filtered day also brings in the NoHarm notes written on it."""
    response = client.get(
        _url(timeline.admission, date=DAY_2.date().isoformat()),
        headers=analyst_headers,
    )

    assert set(_by_id(response.get_json()["data"])) == {
        str(timeline.day2_note),
        str(timeline.day2_noharm),
    }


def test_date_filter_skips_the_dates_and_admissions_blocks(
    client, analyst_headers, timeline
):
    """Asking for one day does not compute the timeline or the admissions."""
    response = client.get(
        _url(timeline.admission, date=DAY_1.date().isoformat()),
        headers=analyst_headers,
    )

    data = response.get_json()["data"]
    assert data["dates"] == []
    assert data["previousAdmissions"] == []


def test_date_filter_on_a_silent_day_returns_no_notes(
    client, analyst_headers, timeline
):
    """A day nobody wrote on answers with an empty note list."""
    response = client.get(
        _url(timeline.admission, date="2024-03-10"), headers=analyst_headers
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"]["notes"] == []


#
# previousAdmissions
#


@pytest.fixture
def patient_with_three_admissions():
    """One patient admitted three times, only the middle stay discharged."""
    id_patient = _next_admission()  # reuse the reserved range for the patient id
    admissions = [
        (_next_admission(), datetime(2024, 1, 10), None),
        (_next_admission(), datetime(2024, 5, 20), datetime(2024, 5, 30)),
        (_next_admission(), datetime(2024, 9, 2), None),
    ]

    for admission, admitted, discharged in admissions:
        _insert_admission(
            admission=admission,
            id_patient=id_patient,
            admitted=admitted,
            discharged=discharged,
        )

    session_commit()

    yield admissions

    for admission, _, _ in admissions:
        session.execute(
            text("DELETE FROM demo.pessoa WHERE nratendimento = :admission"),
            {"admission": admission},
        )
    session_commit()


def test_previous_admissions_are_listed_newest_first(
    client, analyst_headers, patient_with_three_admissions
):
    """Every stay of the patient is listed, most recent admission first."""
    oldest, middle, newest = patient_with_three_admissions

    response = client.get(_url(oldest[0]), headers=analyst_headers)

    assert response.status_code == status.HTTP_200_OK
    listed = response.get_json()["data"]["previousAdmissions"]
    assert [item["admissionNumber"] for item in listed] == [
        newest[0],
        middle[0],
        oldest[0],
    ]


def test_previous_admissions_carry_both_dates(
    client, analyst_headers, patient_with_three_admissions
):
    """A stay reports its admission date and, when it ended, its discharge."""
    oldest, middle, _ = patient_with_three_admissions

    response = client.get(_url(oldest[0]), headers=analyst_headers)

    listed = {
        item["admissionNumber"]: item
        for item in response.get_json()["data"]["previousAdmissions"]
    }
    assert listed[middle[0]]["admissionDate"] == middle[1].isoformat()
    assert listed[middle[0]]["dischargeDate"] == middle[2].isoformat()
    assert listed[oldest[0]]["dischargeDate"] is None


#
# empty admission and authorization
#


def test_unknown_admission_answers_empty(client, analyst_headers):
    """An admission nobody wrote about is answered with empty blocks."""
    response = client.get(_url(999999999), headers=analyst_headers)

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"] == {
        "dates": [],
        "notes": [],
        "previousAdmissions": [],
    }


def test_regulation_permission_is_enough(client, regulator_headers, timeline):
    """READ_REGULATION reads the timeline without READ_PRESCRIPTION."""
    response = client.get(_url(timeline.admission), headers=regulator_headers)

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"]["notes"] != []


def test_requires_prescription_or_regulation_permission(
    client, navigator_headers, timeline
):
    """NAVIGATOR holds neither permission and is refused [401 UNAUTHORIZED]."""
    response = client.get(_url(timeline.admission), headers=navigator_headers)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
