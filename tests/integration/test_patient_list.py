"""Integration tests for the primary-care patient listing endpoints.

Covers ``patient_service.get_patients`` through both routes that reach it —
``GET /patient`` (legacy query-string form) and ``POST /patient/list`` (JSON
body form) — which had no coverage at all.

The listing joins each ``pessoa`` row to its newest aggregated prescription
and decorates it with the most recent "Agendamento" clinical note (the
appointment date, exposed as ``refDate``). Every filter in
``PatientListRequest`` narrows that query, so the fixtures below build a
small, self-contained cohort and each test asserts which of those patients
survive a given filter.

All rows use the 99xxxx id range so they never collide with seed data nor
with the 1000xx range that ``tests/utils/utils_test_prescription.py`` hands
out, and they are removed again in the fixture teardown.
"""

from datetime import datetime

import pytest
from sqlalchemy import text

from models.enums import FeatureEnum
from models.main import User
from security.role import Role
from tests.conftest import get_access, make_headers, session, session_commit

# One admission per patient; ids are reused across the three tables.
ADMISSION_SCHEDULED = 990001
ADMISSION_NOT_SCHEDULED = 990002
ADMISSION_OTHER_SEGMENT = 990003
ADMISSION_DISCHARGED = 990004

_ADMISSIONS = (
    ADMISSION_SCHEDULED,
    ADMISSION_NOT_SCHEDULED,
    ADMISSION_OTHER_SEGMENT,
    ADMISSION_DISCHARGED,
)

# Departments: the cohort is split so idDepartment filtering is observable.
# The prescricao insert trigger derives idsegmento from the department through
# demo.segmentosetor, so the pairs below have to match that seed mapping.
DEPARTMENT_A = 1  # -> segment 1
SEGMENT_A = 1
DEPARTMENT_B = 3  # -> segment 2
SEGMENT_B = 2

# Users referenced by the clinical notes, so scheduledBy/attendedBy differ.
SCHEDULER_USER = 1
ATTENDANT_USER = 2

APPOINTMENT_DATE = datetime(2026, 3, 10, 8, 30)
DISCHARGE_DATE = datetime(2026, 2, 1, 12, 0)

TAG_INCLUDED = "ZZTEST_PMC_INCLUDED"
TAG_EXCLUDED = "ZZTEST_PMC_EXCLUDED"

_NOTE_ID_BASE = 990000


def _insert_patient(admission_number, discharge_date=None, tags=None):
    """Insert a ``pessoa`` row keyed by the given admission number."""
    session.execute(
        text(
            "INSERT INTO demo.pessoa "
            "(fkhospital, fkpessoa, nratendimento, dtnascimento, dtinternacao, "
            "dtalta, marcadores, anotacao) "
            "VALUES (1, :admission, :admission, :birthdate, :admitted, "
            ":discharged, :tags, :observation)"
        ),
        {
            "admission": admission_number,
            "birthdate": datetime(1980, 1, 1),
            "admitted": datetime(2026, 1, 1),
            "discharged": discharge_date,
            "tags": tags,
            "observation": f"observation {admission_number}",
        },
    )


def _insert_prescription(id_prescription, admission_number, id_department):
    """Insert an aggregated ``prescricao`` row for the given admission.

    ``idsegmento`` is left to the insert trigger, which resolves it from the
    department through ``demo.segmentosetor``.
    """
    session.execute(
        text(
            "INSERT INTO demo.prescricao "
            "(fkhospital, fksetor, fkprescricao, fkpessoa, nratendimento, "
            "dtprescricao, agregada, status) "
            "VALUES (1, :department, :id, :admission, :admission, "
            ":date, true, '0')"
        ),
        {
            "id": id_prescription,
            "admission": admission_number,
            "department": id_department,
            "date": datetime(2026, 1, 2),
        },
    )


def _insert_note(id_note, admission_number, position, date, user):
    """Insert an ``evolucao`` row used as an appointment/attendance marker."""
    session.execute(
        text(
            "INSERT INTO demo.evolucao "
            "(fkevolucao, nratendimento, dtevolucao, texto, cargo, exame, update_by) "
            "VALUES (:id, :admission, :date, 'zztest note', :position, false, :user)"
        ),
        {
            "id": id_note,
            "admission": admission_number,
            "date": date,
            "position": position,
            "user": user,
        },
    )


def _delete_cohort():
    """Remove every row the cohort fixture creates."""
    admissions = tuple(_ADMISSIONS)
    session.execute(
        text("DELETE FROM demo.evolucao WHERE nratendimento IN :admissions"),
        {"admissions": admissions},
    )
    session.execute(
        text("DELETE FROM demo.prescricao WHERE nratendimento IN :admissions"),
        {"admissions": admissions},
    )
    session.execute(
        text("DELETE FROM demo.pessoa WHERE nratendimento IN :admissions"),
        {"admissions": admissions},
    )
    session_commit()


@pytest.fixture
def cohort():
    """Build the patient cohort the listing tests filter over.

    - ``ADMISSION_SCHEDULED``: department A, has an "Agendamento" note (so it
      carries a ``refDate``) plus an attendance note.
    - ``ADMISSION_NOT_SCHEDULED``: department A, no notes.
    - ``ADMISSION_OTHER_SEGMENT``: department B (a different segment), no notes.
    - ``ADMISSION_DISCHARGED``: department A, discharged, tagged.

    ``ADMISSION_SCHEDULED`` gets two aggregated prescriptions so the "newest
    aggregated prescription wins" join is exercised too.
    """
    _delete_cohort()

    _insert_patient(ADMISSION_SCHEDULED)
    _insert_patient(ADMISSION_NOT_SCHEDULED)
    _insert_patient(ADMISSION_OTHER_SEGMENT)
    _insert_patient(
        ADMISSION_DISCHARGED,
        discharge_date=DISCHARGE_DATE,
        tags=[TAG_INCLUDED],
    )

    # older aggregated prescription — must lose to the newer one below
    _insert_prescription(
        id_prescription=ADMISSION_SCHEDULED,
        admission_number=ADMISSION_SCHEDULED,
        id_department=DEPARTMENT_A,
    )
    _insert_prescription(
        id_prescription=ADMISSION_SCHEDULED + 500,
        admission_number=ADMISSION_SCHEDULED,
        id_department=DEPARTMENT_A,
    )
    _insert_prescription(
        id_prescription=ADMISSION_NOT_SCHEDULED,
        admission_number=ADMISSION_NOT_SCHEDULED,
        id_department=DEPARTMENT_A,
    )
    _insert_prescription(
        id_prescription=ADMISSION_OTHER_SEGMENT,
        admission_number=ADMISSION_OTHER_SEGMENT,
        id_department=DEPARTMENT_B,
    )
    _insert_prescription(
        id_prescription=ADMISSION_DISCHARGED,
        admission_number=ADMISSION_DISCHARGED,
        id_department=DEPARTMENT_A,
    )

    _insert_note(
        id_note=_NOTE_ID_BASE + 1,
        admission_number=ADMISSION_SCHEDULED,
        position="Agendamento",
        date=APPOINTMENT_DATE,
        user=SCHEDULER_USER,
    )
    _insert_note(
        id_note=_NOTE_ID_BASE + 2,
        admission_number=ADMISSION_SCHEDULED,
        position="Enfermagem",
        date=datetime(2026, 3, 1, 9, 0),
        user=ATTENDANT_USER,
    )

    session_commit()

    yield

    _delete_cohort()


@pytest.fixture
def primary_care_headers(client):
    """Headers for an analyst whose user config enables the PRIMARYCARE flag.

    ``memory_service.has_feature`` accepts a per-user override, so the flag is
    switched on through the demo user's config instead of mutating the shared
    ``features`` memory row. The config is baked into the JWT claims at login,
    so it has to be in place *before* authenticating.
    """
    user = session.query(User).filter_by(email="demo").first()
    original_config = user.config

    user.config = {
        "roles": [Role.PRESCRIPTION_ANALYST.value],
        "features": [
            FeatureEnum.STAGING_ACCESS.value,
            FeatureEnum.PRIMARY_CARE.value,
        ],
    }
    session_commit()

    response = client.post(
        "/authenticate",
        json={"email": "demo", "password": "demo"},
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    assert response.status_code == 200, "demo user must be able to authenticate"

    yield make_headers(response.get_json()["access_token"])

    user.config = original_config
    session_commit()


def _list(client, headers, **filters):
    """POST /patient/list and return the response."""
    return client.post("/patient/list", json=filters, headers=headers)


def _admissions(response):
    """Extract the cohort admission numbers from a successful response."""
    return {
        item["admissionNumber"]
        for item in response.get_json()["data"]
        if item["admissionNumber"] in _ADMISSIONS
    }


def _by_admission(response, admission_number):
    """Return the single listing entry for the given admission number."""
    matches = [
        item
        for item in response.get_json()["data"]
        if item["admissionNumber"] == admission_number
    ]
    assert len(matches) == 1, f"expected exactly one entry for {admission_number}"
    return matches[0]


# --- guards ----------------------------------------------------------------


def test_list_requires_read_prescription(client, cohort):
    """A dispensing manager has no READ_PRESCRIPTION permission [401]."""
    headers = make_headers(get_access(client, roles=[Role.DISPENSING_MANAGER.value]))

    response = _list(client, headers)

    assert response.status_code == 401


def test_list_requires_the_primary_care_feature(client, analyst_headers, cohort):
    """Without the PRIMARYCARE flag the service rejects the request [400]."""
    response = _list(client, analyst_headers)

    assert response.status_code == 400
    assert response.get_json()["message"] == "Funcionalidade não está habilitada"


# --- unfiltered listing ----------------------------------------------------


def test_list_returns_patients_with_an_aggregated_prescription(
    client, primary_care_headers, cohort
):
    """Every cohort patient has an aggregated prescription, so all are listed."""
    response = _list(client, primary_care_headers)

    assert response.status_code == 200
    assert _admissions(response) == set(_ADMISSIONS)


def test_list_serializes_the_patient_payload(client, primary_care_headers, cohort):
    """Each entry carries the patient identity, its observation and its tags."""
    response = _list(client, primary_care_headers)

    entry = _by_admission(response, ADMISSION_DISCHARGED)

    assert entry["idPatient"] == ADMISSION_DISCHARGED
    assert entry["birthdate"] == "1980-01-01"
    assert entry["admissionDate"] == "2026-01-01T00:00:00"
    assert entry["observation"] == f"observation {ADMISSION_DISCHARGED}"
    assert entry["tags"] == [TAG_INCLUDED]


def test_list_picks_the_newest_aggregated_prescription(
    client, primary_care_headers, cohort
):
    """When a patient has several aggregated prescriptions the highest id wins."""
    response = _list(client, primary_care_headers)

    entry = _by_admission(response, ADMISSION_SCHEDULED)

    assert entry["idPrescription"] == ADMISSION_SCHEDULED + 500


def test_list_exposes_the_appointment_date_as_ref_date(
    client, primary_care_headers, cohort
):
    """refDate is the latest "Agendamento" note date, and None without one."""
    response = _list(client, primary_care_headers)

    assert (
        _by_admission(response, ADMISSION_SCHEDULED)["refDate"]
        == APPOINTMENT_DATE.date().isoformat()
    )
    assert _by_admission(response, ADMISSION_NOT_SCHEDULED)["refDate"] is None


# --- filters ---------------------------------------------------------------


def test_list_filters_by_segment(client, primary_care_headers, cohort):
    """idSegment keeps only the patients prescribed in that segment."""
    response = _list(client, primary_care_headers, idSegment=SEGMENT_B)

    assert response.status_code == 200
    assert _admissions(response) == {ADMISSION_OTHER_SEGMENT}


def test_list_filters_by_department(client, primary_care_headers, cohort):
    """idDepartment accepts a list and matches the prescription department."""
    response = _list(client, primary_care_headers, idDepartment=[DEPARTMENT_B])

    assert response.status_code == 200
    assert _admissions(response) == {ADMISSION_OTHER_SEGMENT}


def test_list_filters_scheduled_patients(client, primary_care_headers, cohort):
    """appointment=scheduled keeps only patients holding an appointment."""
    response = _list(client, primary_care_headers, appointment="scheduled")

    assert response.status_code == 200
    assert _admissions(response) == {ADMISSION_SCHEDULED}


def test_list_filters_not_scheduled_patients(client, primary_care_headers, cohort):
    """appointment=not-scheduled is the complement of the scheduled filter."""
    response = _list(client, primary_care_headers, appointment="not-scheduled")

    assert response.status_code == 200
    assert _admissions(response) == set(_ADMISSIONS) - {ADMISSION_SCHEDULED}


def test_list_filters_by_appointment_window(client, primary_care_headers, cohort):
    """A window around the appointment keeps the scheduled patient..."""
    response = _list(
        client,
        primary_care_headers,
        nextAppointmentStartDate="2026-03-01T00:00:00",
        nextAppointmentEndDate="2026-03-31T00:00:00",
    )

    assert response.status_code == 200
    assert _admissions(response) == {ADMISSION_SCHEDULED}


def test_list_appointment_window_excludes_dates_outside_it(
    client, primary_care_headers, cohort
):
    """...and a window that ends before it drops every cohort patient."""
    response = _list(
        client,
        primary_care_headers,
        nextAppointmentStartDate="2026-01-01T00:00:00",
        nextAppointmentEndDate="2026-01-31T00:00:00",
    )

    assert response.status_code == 200
    assert _admissions(response) == set()


def test_list_filters_by_scheduled_by(client, primary_care_headers, cohort):
    """scheduledBy matches the author of the "Agendamento" note only."""
    scheduled = _list(client, primary_care_headers, scheduledBy=[SCHEDULER_USER])
    other = _list(client, primary_care_headers, scheduledBy=[ATTENDANT_USER])

    assert _admissions(scheduled) == {ADMISSION_SCHEDULED}
    assert _admissions(other) == set()


def test_list_filters_by_attended_by(client, primary_care_headers, cohort):
    """attendedBy matches the author of any non-"Agendamento" note."""
    attended = _list(client, primary_care_headers, attendedBy=[ATTENDANT_USER])
    other = _list(client, primary_care_headers, attendedBy=[SCHEDULER_USER])

    assert _admissions(attended) == {ADMISSION_SCHEDULED}
    assert _admissions(other) == set()


def test_list_filters_by_discharge_date_range(client, primary_care_headers, cohort):
    """A discharge range keeps only the discharged patient."""
    response = _list(
        client,
        primary_care_headers,
        dischargeDateStart="2026-01-15T00:00:00",
        dischargeDateEnd="2026-02-15T00:00:00",
    )

    assert response.status_code == 200
    assert _admissions(response) == {ADMISSION_DISCHARGED}


def test_list_filters_by_tags(client, primary_care_headers, cohort):
    """tags overlaps the patient tag array; an unused tag matches nobody."""
    tagged = _list(client, primary_care_headers, tags=[TAG_INCLUDED])
    untagged = _list(client, primary_care_headers, tags=[TAG_EXCLUDED])

    assert _admissions(tagged) == {ADMISSION_DISCHARGED}
    assert _admissions(untagged) == set()


def test_list_combines_filters(client, primary_care_headers, cohort):
    """Filters are additive: the first segment plus scheduled leaves one patient."""
    response = _list(
        client,
        primary_care_headers,
        idSegment=SEGMENT_A,
        appointment="scheduled",
    )

    assert response.status_code == 200
    assert _admissions(response) == {ADMISSION_SCHEDULED}


def test_list_rejects_an_unparsable_filter(client, primary_care_headers, cohort):
    """A non-date value for a date filter fails Pydantic validation [400]."""
    response = _list(client, primary_care_headers, dischargeDateStart="not-a-date")

    assert response.status_code == 400


# --- legacy GET route ------------------------------------------------------


def test_legacy_get_route_lists_the_same_patients(client, primary_care_headers, cohort):
    """GET /patient reaches the same service and honours the same filters."""
    response = client.get(
        f"/patient?idSegment={SEGMENT_B}&appointment=not-scheduled",
        headers=primary_care_headers,
    )

    assert response.status_code == 200
    assert _admissions(response) == {ADMISSION_OTHER_SEGMENT}


def test_legacy_get_route_reads_repeated_department_params(
    client, primary_care_headers, cohort
):
    """The legacy route collects repeated idDepartment[] params into a list."""
    response = client.get(
        f"/patient?idDepartment[]={DEPARTMENT_B}&idDepartment[]={DEPARTMENT_A}",
        headers=primary_care_headers,
    )

    assert response.status_code == 200
    assert _admissions(response) == set(_ADMISSIONS)
