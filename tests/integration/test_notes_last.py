"""Tests: GET /notes/single/<id>, /notes/get-user-last and /notes/get-user-last-list

Three read-only endpoints the prescription screen leans on. ``get-user-last``
and ``get-user-last-list`` answer "what did a pharmacist last write about this
admission?" -- the single most recent note and the last five of them -- and
``single`` fetches one clinical note by id when the user opens it.

The pair matters because it has two entirely different sources depending on a
schema feature. With MULTI_CLINICAL_NOTES off, a prescription carries at most
one note in ``demo.prescricao.evolucao``, so the notes are read from the
prescriptions themselves. With it on, notes are rows in
``demo.prescricao_evolucao`` and a prescription may carry several. The demo
schema has the feature on, so both paths are exercised here -- the second by
taking the flag away for the length of a test.

What these tests pin down:

* the newest note wins, and prescriptions carrying no note are passed over
  rather than answered with an empty note;
* an admission nobody has written about answers with null / an empty list, not
  an error;
* the list is capped at five and ordered newest first, and under
  MULTI_CLINICAL_NOTES an edited note is ordered by when it was edited, not by
  when it was created;
* the feature really does switch the source, so a note stored one way is not
  served while the other way is configured;
* ``single`` returns the note's own fields, cuts a pathologically long text
  rather than shipping it, and refuses an id that does not exist;
* none of the three is readable by a caller without READ_PRESCRIPTION.
"""

import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from models.enums import FeatureEnum
from tests.conftest import session, session_commit
from tests.utils.utils_test_prescription import create_prescription, test_counters
from utils import status

SINGLE_URL = "/notes/single"
LAST_URL = "/notes/get-user-last"
LAST_LIST_URL = "/notes/get-user-last-list"

MULTI = FeatureEnum.MULTI_CLINICAL_NOTES.value

# clinical notes written here; kept above the seed range and wiped per test
CLINICAL_NOTE_ID = 100000

# above every id the test helpers hand out, so no run can make it exist
MISSING_NOTE = 999999999

# clinical_notes_service.convert_notes cuts a text longer than this
MAX_NOTE_LENGTH = 700000


def _next_admission() -> int:
    """Reserve an admission number no other test uses."""
    admission = test_counters["admission_number"]
    test_counters["admission_number"] += 1
    return admission


def _create_prescription_with_note(admission: int, note: str, date: datetime) -> int:
    """Write a prescription carrying `note` in demo.prescricao.evolucao.

    The note is set with an UPDATE because the BEFORE INSERT trigger on
    demo.prescricao rewrites the row through public.upsert_prescricao. Passing
    note=None leaves the column null, which is how a prescription nobody has
    written about looks.
    """
    id_prescription = test_counters["id_prescription"]
    test_counters["id_prescription"] += 1

    create_prescription(
        id=id_prescription, admissionNumber=admission, idPatient=1, date=date
    )

    if note is not None:
        session.execute(
            text(
                "UPDATE demo.prescricao SET evolucao = :note WHERE fkprescricao = :id"
            ),
            {"note": note, "id": id_prescription},
        )
        session_commit()

    return id_prescription


def _create_prescription_note(
    admission: int,
    note: str,
    created_at: datetime,
    updated_at: datetime = None,
) -> int:
    """Write a demo.prescricao_evolucao row -- the MULTI_CLINICAL_NOTES source."""
    id_prescription = _create_prescription_with_note(
        admission=admission, note=None, date=created_at
    )

    session.execute(
        text(
            "INSERT INTO demo.prescricao_evolucao "
            "(fkprescricao, nratendimento, texto, tp_status, created_at, created_by, updated_at) "
            "VALUES (:id_prescription, :admission, :note, 0, :created_at, 1, :updated_at)"
        ),
        {
            "id_prescription": id_prescription,
            "admission": admission,
            "note": note,
            "created_at": created_at,
            "updated_at": updated_at,
        },
    )
    session_commit()

    return id_prescription


def _create_clinical_note(
    admission: int, note: str, date: datetime, prescriber: str, position: str
) -> int:
    """Write a demo.evolucao row -- what /notes/single reads."""
    session.execute(
        text(
            "INSERT INTO demo.evolucao "
            "(fkevolucao, nratendimento, texto, dtevolucao, prescritor, cargo, exame) "
            "VALUES (:id, :admission, :note, :date, :prescriber, :position, false)"
        ),
        {
            "id": CLINICAL_NOTE_ID,
            "admission": admission,
            "note": note,
            "date": date,
            "prescriber": prescriber,
            "position": position,
        },
    )
    session_commit()

    return CLINICAL_NOTE_ID


def _read_features() -> list:
    """The feature list currently stored in the demo schema."""
    row = session.execute(
        text("SELECT valor FROM demo.memoria WHERE tipo = 'features'")
    ).first()
    return list(row[0]) if row else []


def _write_features(features: list):
    """Overwrite the demo schema feature list."""
    session.execute(
        text(
            "UPDATE demo.memoria SET valor = CAST(:value AS json) WHERE tipo = 'features'"
        ),
        {"value": json.dumps(features)},
    )
    session_commit()


@pytest.fixture
def single_notes_source():
    """Take MULTI_CLINICAL_NOTES away, so notes come from the prescriptions."""
    original = _read_features()
    _write_features([f for f in original if f != MULTI])
    yield
    _write_features(original)


@pytest.fixture(autouse=True)
def clean_notes():
    """Drop the notes this module writes -- tests.conftest does not know them."""
    yield
    session.execute(
        text("DELETE FROM demo.prescricao_evolucao WHERE nratendimento >= 100000")
    )
    session.execute(text("DELETE FROM demo.evolucao WHERE fkevolucao >= 100000"))
    session_commit()


#
# GET /notes/get-user-last
#


def test_get_user_last_returns_the_most_recent_note(
    client, analyst_headers, single_notes_source
):
    """Teste get /notes/get-user-last - Deve retornar a evolução da prescrição mais recente"""
    admission = _next_admission()
    now = datetime.now()

    _create_prescription_with_note(admission, "nota antiga", now - timedelta(days=2))
    _create_prescription_with_note(admission, "nota recente", now)

    response = client.get(
        LAST_URL, query_string={"admissionNumber": admission}, headers=analyst_headers
    )

    assert response.status_code == status.HTTP_200_OK

    data = response.get_json()["data"]
    assert data["text"] == "nota recente"
    assert datetime.fromisoformat(data["date"])


def test_get_user_last_skips_prescriptions_without_a_note(
    client, analyst_headers, single_notes_source
):
    """Teste get /notes/get-user-last - Deve ignorar prescrições sem evolução"""
    admission = _next_admission()
    now = datetime.now()

    _create_prescription_with_note(admission, "unica nota", now - timedelta(days=2))
    # newer, but nobody wrote about it
    _create_prescription_with_note(admission, None, now)

    response = client.get(
        LAST_URL, query_string={"admissionNumber": admission}, headers=analyst_headers
    )

    assert response.get_json()["data"]["text"] == "unica nota"


def test_get_user_last_returns_null_when_nothing_was_written(
    client, analyst_headers, single_notes_source
):
    """Teste get /notes/get-user-last - Atendimento sem evolução deve retornar nulo"""
    admission = _next_admission()
    _create_prescription_with_note(admission, None, datetime.now())

    response = client.get(
        LAST_URL, query_string={"admissionNumber": admission}, headers=analyst_headers
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"] is None


def test_get_user_last_requires_read_prescription(client, user_manager_headers):
    """Teste get /notes/get-user-last - Usuário sem READ_PRESCRIPTION deve receber [401 UNAUTHORIZED]"""
    response = client.get(
        LAST_URL,
        query_string={"admissionNumber": _next_admission()},
        headers=user_manager_headers,
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


#
# GET /notes/get-user-last-list
#


def test_get_user_last_list_returns_notes_newest_first(client, analyst_headers):
    """Teste get /notes/get-user-last-list - Deve listar as evoluções da mais recente para a mais antiga"""
    admission = _next_admission()
    now = datetime.now()

    _create_prescription_note(admission, "primeira", now - timedelta(days=2))
    _create_prescription_note(admission, "segunda", now - timedelta(days=1))
    _create_prescription_note(admission, "terceira", now)

    response = client.get(
        LAST_LIST_URL,
        query_string={"admissionNumber": admission},
        headers=analyst_headers,
    )

    assert response.status_code == status.HTTP_200_OK
    assert [n["text"] for n in response.get_json()["data"]] == [
        "terceira",
        "segunda",
        "primeira",
    ]


def test_get_user_last_list_returns_at_most_five_notes(client, analyst_headers):
    """Teste get /notes/get-user-last-list - Deve retornar no máximo cinco evoluções"""
    admission = _next_admission()
    now = datetime.now()

    for i in range(7):
        _create_prescription_note(admission, f"nota {i}", now - timedelta(days=i))

    response = client.get(
        LAST_LIST_URL,
        query_string={"admissionNumber": admission},
        headers=analyst_headers,
    )

    data = response.get_json()["data"]
    assert len(data) == 5
    # the five newest, so the two oldest are the ones dropped
    assert [n["text"] for n in data] == [
        "nota 0",
        "nota 1",
        "nota 2",
        "nota 3",
        "nota 4",
    ]


def test_get_user_last_list_orders_an_edited_note_by_its_edit_date(
    client, analyst_headers
):
    """Teste get /notes/get-user-last-list - Uma evolução editada é ordenada pela data de edição"""
    admission = _next_admission()
    now = datetime.now()

    # written first but edited last, so it must come out on top
    _create_prescription_note(
        admission,
        "editada",
        created_at=now - timedelta(days=5),
        updated_at=now,
    )
    # never edited, so it is ordered by its creation date
    _create_prescription_note(admission, "intocada", created_at=now - timedelta(days=1))

    response = client.get(
        LAST_LIST_URL,
        query_string={"admissionNumber": admission},
        headers=analyst_headers,
    )

    assert [n["text"] for n in response.get_json()["data"]] == ["editada", "intocada"]


def test_get_user_last_list_returns_empty_when_nothing_was_written(
    client, analyst_headers
):
    """Teste get /notes/get-user-last-list - Atendimento sem evolução deve retornar lista vazia"""
    response = client.get(
        LAST_LIST_URL,
        query_string={"admissionNumber": _next_admission()},
        headers=analyst_headers,
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"] == []


def test_get_user_last_list_reads_prescriptions_without_the_multi_feature(
    client, analyst_headers, single_notes_source
):
    """Teste get /notes/get-user-last-list - Sem MULTI_CLINICAL_NOTES a origem são as prescrições"""
    admission = _next_admission()
    now = datetime.now()

    _create_prescription_with_note(admission, "nota da prescricao", now)
    # stored in the other source, so it must not show up
    _create_prescription_note(admission, "nota multipla", now)

    response = client.get(
        LAST_LIST_URL,
        query_string={"admissionNumber": admission},
        headers=analyst_headers,
    )

    assert [n["text"] for n in response.get_json()["data"]] == ["nota da prescricao"]


def test_get_user_last_list_reads_prescription_notes_with_the_multi_feature(
    client, analyst_headers
):
    """Teste get /notes/get-user-last-list - Com MULTI_CLINICAL_NOTES a origem é prescricao_evolucao"""
    admission = _next_admission()
    now = datetime.now()

    _create_prescription_with_note(admission, "nota da prescricao", now)
    _create_prescription_note(admission, "nota multipla", now)

    response = client.get(
        LAST_LIST_URL,
        query_string={"admissionNumber": admission},
        headers=analyst_headers,
    )

    assert [n["text"] for n in response.get_json()["data"]] == ["nota multipla"]


def test_get_user_last_list_requires_read_prescription(client, user_manager_headers):
    """Teste get /notes/get-user-last-list - Usuário sem READ_PRESCRIPTION deve receber [401 UNAUTHORIZED]"""
    response = client.get(
        LAST_LIST_URL,
        query_string={"admissionNumber": _next_admission()},
        headers=user_manager_headers,
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


#
# GET /notes/single/<id>
#


def test_get_single_note_returns_the_note(client, analyst_headers):
    """Teste get /notes/single/<id> - Deve retornar os dados da evolução"""
    admission = _next_admission()
    date = datetime(2024, 3, 4, 5, 6, 7)

    id_note = _create_clinical_note(
        admission=admission,
        note="texto da evolucao",
        date=date,
        prescriber="Dr. Teste",
        position="MEDICO",
    )

    response = client.get(f"{SINGLE_URL}/{id_note}", headers=analyst_headers)

    assert response.status_code == status.HTTP_200_OK

    data = response.get_json()["data"]
    assert data["id"] == str(id_note)
    assert data["admissionNumber"] == admission
    assert data["text"] == "texto da evolucao"
    assert data["date"] == date.isoformat()
    assert data["prescriber"] == "Dr. Teste"
    assert data["position"] == "MEDICO"
    # the primary-care fields are never filled by this endpoint
    assert data["form"] is None
    assert data["template"] is None


def test_get_single_note_cuts_a_very_long_text(client, analyst_headers):
    """Teste get /notes/single/<id> - Texto muito longo deve ser cortado"""
    id_note = _create_clinical_note(
        admission=_next_admission(),
        note="a" * (MAX_NOTE_LENGTH + 10),
        date=datetime.now(),
        prescriber="Dr. Teste",
        position="MEDICO",
    )

    response = client.get(f"{SINGLE_URL}/{id_note}", headers=analyst_headers)

    assert (
        response.get_json()["data"]["text"]
        == "a" * MAX_NOTE_LENGTH + "<p>Evolução cortada por texto muito longo.</p>"
    )


def test_get_single_note_rejects_a_missing_note(client, analyst_headers):
    """Teste get /notes/single/<id> - Evolução inexistente deve retornar erro [400 BAD REQUEST]"""
    response = client.get(f"{SINGLE_URL}/{MISSING_NOTE}", headers=analyst_headers)

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_get_single_note_requires_read_prescription(client, user_manager_headers):
    """Teste get /notes/single/<id> - Usuário sem READ_PRESCRIPTION deve receber [401 UNAUTHORIZED]"""
    id_note = _create_clinical_note(
        admission=_next_admission(),
        note="texto da evolucao",
        date=datetime.now(),
        prescriber="Dr. Teste",
        position="MEDICO",
    )

    response = client.get(f"{SINGLE_URL}/{id_note}", headers=user_manager_headers)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
