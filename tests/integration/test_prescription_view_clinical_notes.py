"""Integration tests for the clinical-notes section of the prescription screen.

``GET /prescriptions/<id>`` carries, besides the drugs, everything the
pharmacist needs to read the patient's chart: the latest vital signs and
patient info, the allergies and dialysis sessions recorded in the care notes,
and the per-tag counts that drive the screen's note badges. All of it is
extracted from ``demo.evolucao`` by ``repository/clinical_notes_repository``.

The seed database has no clinical notes at all, so every one of those queries
ran against an empty table and returned nothing: the extraction rules were
covered only in the sense that the SQL parsed. They are not incidental —
each one exists to keep a busy chart readable:

* signs and info are the single most recent note that carries them, within 60
  days, and signs are only looked up when the note stats say there are any;
* allergies are folded by text so a term repeated across a stay is listed
  once, dated by its most recent mention, and cut off at the admission date so
  a previous stay's allergies do not leak in;
* dialysis is reported at most once per calendar day — the last session of
  that day — over the last three days;
* the stats sum each tag's count across the admission's notes of the last six
  days, skipping notes that are really exam results.

These tests seed real notes and assert what the screen receives. They read the
database path deliberately: ``cache_service`` is inert under ``ENV=test``, so
the cache branches belong to unit tests, and this is the path a schema runs
with the Redis cache turned off.

Notes use ids ``>= 900000`` and are removed by this module; prescriptions and
admissions come from ``test_counters`` (ids >= 100000), which
``clean_test_artifacts`` wipes.
"""

import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from models.prescription import Patient
from tests.conftest import session, session_commit
from tests.utils.utils_test_prescription import create_basic_prescription
from utils import status

# Ids reserved for the notes this module inserts. The seed has none, so the
# range only has to stay clear of anything a future fixture might add.
_FIRST_NOTE_ID = 900000

_note_ids = iter(range(_FIRST_NOTE_ID, _FIRST_NOTE_ID + 10000))


@pytest.fixture(autouse=True)
def clean_clinical_notes():
    """Remove the notes this module inserts, before and after each test."""
    _delete_test_notes()

    yield

    _delete_test_notes()


def _delete_test_notes():
    session.execute(
        text("DELETE FROM demo.evolucao WHERE fkevolucao >= :first"),
        {"first": _FIRST_NOTE_ID},
    )
    session_commit()


def _add_note(
    admission_number: int,
    *,
    days_ago: int = 1,
    hour: int = 12,
    signs=None,
    info=None,
    allergy=None,
    dialysis=None,
    counts: dict = None,
    is_exam=None,
) -> int:
    """Insert one clinical note for an admission and return its id.

    The timestamp is anchored to a whole day and hour rather than offset from
    "now", so which calendar day a note lands on never depends on the clock
    the suite happens to run at — the dialysis rules group by exactly that.

    ``counts`` is written to ``anotacoes`` in the ``<tag>_count`` shape the
    note processor produces, which is what the stats query sums.
    """
    id_note = next(_note_ids)
    note_date = datetime.now().replace(
        hour=hour, minute=0, second=0, microsecond=0
    ) - timedelta(days=days_ago)

    session.execute(
        text(
            "INSERT INTO demo.evolucao "
            "(fkevolucao, nratendimento, dtevolucao, texto, sinaistexto, "
            "dadostexto, alergiatexto, dialisetexto, exame, anotacoes) "
            "VALUES (:id, :admission, :date, 'ZZTest evolução', :signs, :info, "
            ":allergy, :dialysis, :is_exam, CAST(:annotations AS jsonb))"
        ),
        {
            "id": id_note,
            "admission": admission_number,
            "date": note_date,
            "signs": signs,
            "info": info,
            "allergy": allergy,
            "dialysis": dialysis,
            "is_exam": is_exam,
            "annotations": json.dumps(counts) if counts is not None else None,
        },
    )
    session_commit()

    return id_note


def _set_admission_date(prescription, days_ago: int):
    """Give the prescription's admission a start date (``demo.pessoa``)."""
    patient = Patient()
    patient.admissionNumber = prescription.admissionNumber
    patient.idPatient = prescription.idPatient
    patient.idHospital = 1
    patient.admissionDate = datetime.now() - timedelta(days=days_ago)

    session.add(patient)
    session_commit()


def _view(client, headers, prescription):
    """Read the prescription screen the notes are rendered on."""
    response = client.get(f"/prescriptions/{prescription.id}", headers=headers)

    assert response.status_code == status.HTTP_200_OK

    return response.get_json()["data"]


def _texts(entries) -> list:
    """The texts of an allergy or dialysis list, in the order returned."""
    return [entry["text"] for entry in entries]


def test_signs_and_info_come_from_the_most_recent_note(client, analyst_headers):
    """A chart holds many notes; the screen shows the newest of each kind."""
    prescription = create_basic_prescription()
    _add_note(
        prescription.admissionNumber,
        days_ago=3,
        signs="PA 130x90",
        info="Paciente sonolento",
    )
    newest = _add_note(
        prescription.admissionNumber,
        days_ago=1,
        signs="PA 120x80",
        info="Paciente estável",
        counts={"sinais_count": 1, "dados_count": 1},
    )

    data = _view(client, analyst_headers, prescription)

    assert data["notesSigns"] == "PA 120x80"
    assert data["notesSignsId"] == str(newest)
    assert data["notesInfo"] == "Paciente estável"
    assert data["notesInfoId"] == str(newest)
    # the value was read from the database, not served from Redis
    assert data["notesSignsCache"] is False
    assert data["notesInfoCache"] is False


def test_signs_and_info_are_taken_from_different_notes(client, analyst_headers):
    """Each kind is searched on its own: the newest note may carry only one."""
    prescription = create_basic_prescription()
    with_info = _add_note(
        prescription.admissionNumber, days_ago=2, info="Paciente acamado"
    )
    with_signs = _add_note(
        prescription.admissionNumber,
        days_ago=1,
        signs="FC 78",
        counts={"sinais_count": 1},
    )

    data = _view(client, analyst_headers, prescription)

    assert data["notesSignsId"] == str(with_signs)
    assert data["notesInfoId"] == str(with_info)


def test_signs_are_not_looked_up_when_the_stats_report_none(client, analyst_headers):
    """The stats gate the lookup, so an unprocessed note stays out of the screen."""
    prescription = create_basic_prescription()
    # carries the text but was never tagged, so the stats count no signs
    _add_note(
        prescription.admissionNumber,
        days_ago=1,
        signs="PA 120x80",
        info="Paciente estável",
    )

    data = _view(client, analyst_headers, prescription)

    assert data["clinicalNotesStats"]["signs"] == 0
    assert data["notesSigns"] == ""
    assert data["notesSignsId"] is None
    # info is read unconditionally, so it is there either way
    assert data["notesInfo"] == "Paciente estável"


def test_signs_older_than_the_window_are_not_shown(client, analyst_headers):
    """Vital signs from two months ago say nothing about today's prescription."""
    prescription = create_basic_prescription()
    _add_note(prescription.admissionNumber, days_ago=61, signs="PA 200x110")
    # a recent tagged note makes the screen ask for signs at all
    _add_note(prescription.admissionNumber, days_ago=1, counts={"sinais_count": 1})

    data = _view(client, analyst_headers, prescription)

    assert data["clinicalNotesStats"]["signs"] == 1
    assert data["notesSigns"] == ""


def test_allergies_repeated_across_notes_are_listed_once(client, analyst_headers):
    """The same allergy is re-copied into every note; the screen shows one."""
    prescription = create_basic_prescription()
    _add_note(prescription.admissionNumber, days_ago=4, allergy="Dipirona")
    latest_mention = _add_note(
        prescription.admissionNumber, days_ago=1, allergy="Dipirona"
    )

    data = _view(client, analyst_headers, prescription)

    assert _texts(data["notesAllergies"]) == ["Dipirona"]
    # dated and identified by the most recent mention
    assert data["notesAllergies"][0]["id"] == str(latest_mention)
    assert data["notesAllergies"][0]["source"] == "care"
    assert data["notesAllergies"][0]["cache"] is False


def test_allergies_are_ordered_by_their_latest_mention(client, analyst_headers):
    """Most recently mentioned first, so the newest finding leads the list."""
    prescription = create_basic_prescription()
    _add_note(prescription.admissionNumber, days_ago=5, allergy="Penicilina")
    _add_note(prescription.admissionNumber, days_ago=3, allergy="Sulfa")
    _add_note(prescription.admissionNumber, days_ago=1, allergy="Penicilina")

    data = _view(client, analyst_headers, prescription)

    assert _texts(data["notesAllergies"]) == ["Penicilina", "Sulfa"]
    assert data["notesAllergiesDate"] == data["notesAllergies"][0]["date"]


def test_allergies_recorded_before_the_admission_are_dropped(client, analyst_headers):
    """A previous stay's notes share the chart but not this admission."""
    prescription = create_basic_prescription()
    _set_admission_date(prescription, days_ago=5)
    _add_note(prescription.admissionNumber, days_ago=30, allergy="Alergia anterior")
    _add_note(prescription.admissionNumber, days_ago=2, allergy="Alergia atual")

    data = _view(client, analyst_headers, prescription)

    assert _texts(data["notesAllergies"]) == ["Alergia atual"]


def test_dialysis_shows_the_last_session_of_each_day(client, analyst_headers):
    """A day may be noted several times; only its final state is reported."""
    prescription = create_basic_prescription()
    _add_note(prescription.admissionNumber, days_ago=1, hour=8, dialysis="HD iniciada")
    last_of_yesterday = _add_note(
        prescription.admissionNumber, days_ago=1, hour=14, dialysis="HD concluída"
    )
    day_before = _add_note(
        prescription.admissionNumber, days_ago=2, dialysis="HD anteontem"
    )

    data = _view(client, analyst_headers, prescription)

    # one entry per calendar day, newest day first
    assert _texts(data["notesDialysis"]) == ["HD concluída", "HD anteontem"]
    assert data["notesDialysis"][0]["id"] == str(last_of_yesterday)
    assert data["notesDialysis"][1]["id"] == str(day_before)
    assert data["notesDialysis"][0]["cache"] is False
    assert data["notesDialysisDate"] == data["notesDialysis"][0]["date"]


def test_dialysis_older_than_three_days_is_not_shown(client, analyst_headers):
    """Only the sessions close enough to matter for today's prescription."""
    prescription = create_basic_prescription()
    _add_note(prescription.admissionNumber, days_ago=4, dialysis="HD antiga")
    _add_note(prescription.admissionNumber, days_ago=1, dialysis="HD recente")

    data = _view(client, analyst_headers, prescription)

    assert _texts(data["notesDialysis"]) == ["HD recente"]


def test_note_stats_sum_each_tag_across_the_admission(client, analyst_headers):
    """The badges count findings over the whole admission, not one note."""
    prescription = create_basic_prescription()
    _add_note(
        prescription.admissionNumber,
        days_ago=1,
        counts={"sinais_count": 2, "alergia_count": 1},
    )
    _add_note(
        prescription.admissionNumber,
        days_ago=2,
        counts={"sinais_count": 3, "dialise_count": 4},
    )

    stats = _view(client, analyst_headers, prescription)["clinicalNotesStats"]

    assert stats["signs"] == 5
    assert stats["allergy"] == 1
    assert stats["dialysis"] == 4
    # a tag no note mentioned still reports a count, so the screen can render it
    assert stats["germs"] == 0


def test_note_stats_ignore_notes_that_are_exam_results(client, analyst_headers):
    """Exam results travel through the same table but are not chart notes."""
    prescription = create_basic_prescription()
    _add_note(prescription.admissionNumber, days_ago=1, counts={"sinais_count": 2})
    _add_note(
        prescription.admissionNumber,
        days_ago=1,
        hour=18,
        counts={"sinais_count": 9},
        is_exam=True,
    )

    stats = _view(client, analyst_headers, prescription)["clinicalNotesStats"]

    assert stats["signs"] == 2


def test_note_stats_ignore_notes_older_than_the_window(client, analyst_headers):
    """The badges describe the current picture, so old notes stop counting."""
    prescription = create_basic_prescription()
    _add_note(prescription.admissionNumber, days_ago=7, counts={"sinais_count": 8})
    _add_note(prescription.admissionNumber, days_ago=1, counts={"sinais_count": 2})

    stats = _view(client, analyst_headers, prescription)["clinicalNotesStats"]

    assert stats["signs"] == 2


def test_an_admission_without_notes_renders_empty_sections(client, analyst_headers):
    """Nothing written yet is the normal state of a fresh admission."""
    prescription = create_basic_prescription()

    data = _view(client, analyst_headers, prescription)

    assert data["notesSigns"] == ""
    assert data["notesInfo"] == ""
    assert data["notesAllergies"] == []
    assert data["notesDialysis"] == []
    assert data["notesAllergiesDate"] is None
    assert data["notesDialysisDate"] is None
    # with no note to sum, every badge comes back empty rather than zero —
    # "pregnant" excepted, which the view pins to 0 for this patient
    stats = data["clinicalNotesStats"]
    assert stats["pregnant"] == 0
    assert set(value for key, value in stats.items() if key != "pregnant") == {None}
