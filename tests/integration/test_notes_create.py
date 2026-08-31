"""Tests: POST /notes and POST /notes/<idNote> (clinical note authoring).

The two endpoints that let a user *write* a clinical note, as opposed to the
read endpoints covered in test_notes_last.py. Both live in
``clinical_notes_service`` and both are gated twice: by the WRITE_PRESCRIPTION
permission and by the schema's PRIMARYCARE feature, which the demo schema does
not carry -- so the tests that need it switch it on for their duration.

What these tests pin down:

* ``POST /notes`` refuses to write anything unless PRIMARYCARE is on, and
  refuses a caller without WRITE_PRESCRIPTION;
* a created note takes its id from the schema's own ``evolucao`` sequence (a
  fresh one per note), records the *author's* name as the prescriber rather
  than anything the caller sent, and stores the primary-care form/template
  payloads as they arrived;
* the note's position is "Farmacêutica" by default, the caller's ``tplName``
  when one is sent, and "Agendamento" for a scheduling note -- the scheduling
  action wins over ``tplName``;
* the date defaults to now when the body omits it and is honoured when sent;
* ``POST /notes/<idNote>`` refuses an id that does not exist, replaces the text
  and re-counts the allergy annotations embedded in it, and leaves the text
  alone when the body does not carry one;
* date and form on an edit are primary-care-only: with the feature off they are
  ignored, with it on they are applied.
"""

import json
from datetime import datetime

import pytest
from sqlalchemy import text

from models.notes import ClinicalNotes
from tests.conftest import session, session_commit
from utils import status

NOTES_URL = "/notes"

PRIMARY_CARE = "PRIMARYCARE"

# the demo user, who authenticates every request in this module
AUTHOR_ID = 1
AUTHOR_NAME = "Demonstração"

# Reserved for this module. The seed data stops well below it and the shared
# counter in tests.utils.utils_test_prescription hands out admission numbers from
# 100000 upwards, one per prescription, so it cannot reach here. tests.conftest
# never touches demo.evolucao, so clean_notes below wipes what this module writes.
ADMISSION = 190000

MISSING_NOTE = 999999999


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
def primary_care():
    """Turn PRIMARYCARE on for the demo schema, as a primary-care client has it."""
    original = _read_features()
    _write_features(original + [PRIMARY_CARE])
    yield
    _write_features(original)


@pytest.fixture(autouse=True)
def clean_notes():
    """Drop the notes this module writes -- tests.conftest does not know them."""
    yield
    session.execute(
        text("DELETE FROM demo.evolucao WHERE nratendimento = :admission"),
        {"admission": ADMISSION},
    )
    session_commit()


def _notes() -> list:
    """Every note written for the test admission, oldest id first."""
    session.expire_all()
    return (
        session.query(ClinicalNotes)
        .filter(ClinicalNotes.admissionNumber == ADMISSION)
        .order_by(ClinicalNotes.id)
        .all()
    )


def _create_note(text_value="nota", **extra) -> int:
    """Write a note straight to the database and return its id.

    Used by the edit tests, which need a note to exist without depending on the
    create endpoint they are not exercising.
    """
    row = session.execute(
        text(
            "INSERT INTO demo.evolucao "
            "(fkevolucao, nratendimento, texto, dtevolucao, prescritor, cargo, exame, formulario) "
            "VALUES (NEXTVAL('demo.evolucao_fkevolucao_seq'), :admission, :note, :date, "
            ":prescriber, :position, false, CAST(:form AS jsonb)) "
            "RETURNING fkevolucao"
        ),
        {
            "admission": ADMISSION,
            "note": text_value,
            "date": extra.get("date", datetime(2026, 1, 5, 9, 0)),
            "prescriber": extra.get("prescriber", "Dr. Test"),
            "position": extra.get("position", "Farmacêutica"),
            "form": json.dumps(extra.get("form")) if extra.get("form") else None,
        },
    ).first()
    session_commit()

    return row[0]


#
# POST /notes -- create
#


def test_create_requires_the_primarycare_feature(client, analyst_headers):
    """Teste post /notes - Deve recusar a criação quando a feature PRIMARYCARE está desligada"""
    response = client.post(
        NOTES_URL,
        json={"admissionNumber": ADMISSION, "notes": "nota"},
        headers=analyst_headers,
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert _notes() == []


def test_create_requires_write_prescription(client, viewer_headers, primary_care):
    """Teste post /notes - Deve retornar erro [401 UNAUTHORIZED] para usuário sem WRITE_PRESCRIPTION"""
    response = client.post(
        NOTES_URL,
        json={"admissionNumber": ADMISSION, "notes": "nota"},
        headers=viewer_headers,
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert _notes() == []


def test_create_persists_the_note(client, analyst_headers, primary_care):
    """Teste post /notes - Deve gravar a evolução com o texto, o autor e o atendimento enviados"""
    response = client.post(
        NOTES_URL,
        json={"admissionNumber": ADMISSION, "notes": "paciente estável"},
        headers=analyst_headers,
    )

    assert response.status_code == status.HTTP_200_OK

    notes = _notes()
    assert len(notes) == 1

    note = notes[0]
    assert note.admissionNumber == ADMISSION
    assert note.text == "paciente estável"
    assert note.user == AUTHOR_ID
    # the author is read from the database, not taken from the request body
    assert note.prescriber == AUTHOR_NAME
    # the created id is echoed back to the caller
    assert response.get_json()["data"] == note.id


def test_create_defaults_the_position_to_the_pharmacist_role(
    client, analyst_headers, primary_care
):
    """Teste post /notes - Sem tplName o cargo deve ser 'Farmacêutica'"""
    client.post(
        NOTES_URL,
        json={"admissionNumber": ADMISSION, "notes": "nota"},
        headers=analyst_headers,
    )

    assert _notes()[0].position == "Farmacêutica"


def test_create_uses_the_template_name_as_the_position(
    client, analyst_headers, primary_care
):
    """Teste post /notes - O tplName enviado deve virar o cargo da evolução"""
    client.post(
        NOTES_URL,
        json={
            "admissionNumber": ADMISSION,
            "notes": "nota",
            "tplName": "Consulta Médica",
        },
        headers=analyst_headers,
    )

    assert _notes()[0].position == "Consulta Médica"


def test_create_marks_a_scheduling_note(client, analyst_headers, primary_care):
    """Teste post /notes - A ação 'schedule' deve prevalecer sobre o tplName e marcar o cargo como 'Agendamento'"""
    client.post(
        NOTES_URL,
        json={
            "admissionNumber": ADMISSION,
            "notes": "retorno em 30 dias",
            "action": "schedule",
            "tplName": "Consulta Médica",
        },
        headers=analyst_headers,
    )

    assert _notes()[0].position == "Agendamento"


def test_create_stores_the_form_and_template(client, analyst_headers, primary_care):
    """Teste post /notes - Os campos formValues e template devem ser gravados como enviados"""
    form = {"pressao": "120/80", "peso": 70}
    template = [{"id": 1, "label": "Pressão"}]

    client.post(
        NOTES_URL,
        json={
            "admissionNumber": ADMISSION,
            "notes": "nota",
            "formValues": form,
            "template": template,
        },
        headers=analyst_headers,
    )

    note = _notes()[0]
    assert note.form == form
    assert note.template == template


def test_create_defaults_the_date_to_now(client, analyst_headers, primary_care):
    """Teste post /notes - Sem data enviada a evolução deve ser datada de hoje"""
    client.post(
        NOTES_URL,
        json={"admissionNumber": ADMISSION, "notes": "nota"},
        headers=analyst_headers,
    )

    assert _notes()[0].date.date() == datetime.today().date()


def test_create_honours_the_given_date(client, analyst_headers, primary_care):
    """Teste post /notes - A data enviada deve ser usada no lugar da data de hoje"""
    client.post(
        NOTES_URL,
        json={
            "admissionNumber": ADMISSION,
            "notes": "nota",
            "date": "2026-02-03T14:25:00",
        },
        headers=analyst_headers,
    )

    assert _notes()[0].date == datetime(2026, 2, 3, 14, 25)


def test_create_hands_out_a_new_id_for_every_note(
    client, analyst_headers, primary_care
):
    """Teste post /notes - Cada evolução deve receber um id novo da sequência do schema"""
    first = client.post(
        NOTES_URL,
        json={"admissionNumber": ADMISSION, "notes": "primeira"},
        headers=analyst_headers,
    ).get_json()["data"]
    second = client.post(
        NOTES_URL,
        json={"admissionNumber": ADMISSION, "notes": "segunda"},
        headers=analyst_headers,
    ).get_json()["data"]

    assert first != second
    assert [n.id for n in _notes()] == sorted([first, second])


#
# POST /notes/<idNote> -- edit
#


def test_update_rejects_an_unknown_note(client, analyst_headers):
    """Teste post /notes/<idNote> - Deve retornar erro [400 BAD REQUEST] para uma evolução inexistente"""
    response = client.post(
        f"{NOTES_URL}/{MISSING_NOTE}", json={"text": "nota"}, headers=analyst_headers
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_update_requires_write_prescription(client, viewer_headers):
    """Teste post /notes/<idNote> - Deve retornar erro [401 UNAUTHORIZED] para usuário sem WRITE_PRESCRIPTION"""
    id_note = _create_note("texto original")

    response = client.post(
        f"{NOTES_URL}/{id_note}", json={"text": "novo texto"}, headers=viewer_headers
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert _notes()[0].text == "texto original"


def test_update_replaces_the_text_and_stamps_the_author(client, analyst_headers):
    """Teste post /notes/<idNote> - Deve gravar o novo texto e registrar quem editou"""
    id_note = _create_note("texto original")

    response = client.post(
        f"{NOTES_URL}/{id_note}", json={"text": "novo texto"}, headers=analyst_headers
    )

    assert response.status_code == status.HTTP_200_OK

    note = _notes()[0]
    assert note.text == "novo texto"
    assert note.user == AUTHOR_ID
    assert note.update.date() == datetime.today().date()


def test_update_counts_the_allergy_annotations(client, analyst_headers):
    """Teste post /notes/<idNote> - O contador de alergias deve refletir as marcações do novo texto"""
    id_note = _create_note("texto original")

    client.post(
        f"{NOTES_URL}/{id_note}",
        json={
            "text": (
                'alergia a <span class="annotation-alergia">dipirona</span> e a '
                '<span class="annotation-alergia">penicilina</span>'
            )
        },
        headers=analyst_headers,
    )

    assert _notes()[0].allergy == 2


def test_update_clears_the_allergy_count_when_the_annotations_go_away(
    client, analyst_headers
):
    """Teste post /notes/<idNote> - Um texto sem marcações deve zerar o contador de alergias"""
    id_note = _create_note('<span class="annotation-alergia">dipirona</span>')
    client.post(
        f"{NOTES_URL}/{id_note}",
        json={"text": '<span class="annotation-alergia">dipirona</span>'},
        headers=analyst_headers,
    )
    assert _notes()[0].allergy == 1

    client.post(
        f"{NOTES_URL}/{id_note}", json={"text": "sem alergias"}, headers=analyst_headers
    )

    assert _notes()[0].allergy == 0


def test_update_keeps_the_text_when_it_is_not_sent(client, analyst_headers):
    """Teste post /notes/<idNote> - Um corpo sem 'text' não deve apagar o texto da evolução"""
    id_note = _create_note("texto original")

    response = client.post(f"{NOTES_URL}/{id_note}", json={}, headers=analyst_headers)

    assert response.status_code == status.HTTP_200_OK
    assert _notes()[0].text == "texto original"


def test_update_ignores_the_date_and_form_without_primarycare(client, analyst_headers):
    """Teste post /notes/<idNote> - Sem PRIMARYCARE a data e o formulário enviados devem ser ignorados"""
    id_note = _create_note("texto original", form={"peso": 70})

    client.post(
        f"{NOTES_URL}/{id_note}",
        json={
            "text": "novo texto",
            "date": "2026-02-03T14:25:00",
            "form": {"peso": 80},
        },
        headers=analyst_headers,
    )

    note = _notes()[0]
    assert note.text == "novo texto"
    assert note.date == datetime(2026, 1, 5, 9, 0)
    assert note.form == {"peso": 70}


def test_update_applies_the_date_and_form_with_primarycare(
    client, analyst_headers, primary_care
):
    """Teste post /notes/<idNote> - Com PRIMARYCARE a data e o formulário enviados devem ser gravados"""
    id_note = _create_note("texto original", form={"peso": 70})

    client.post(
        f"{NOTES_URL}/{id_note}",
        json={
            "text": "novo texto",
            "date": "2026-02-03T14:25:00",
            "form": {"peso": 80},
        },
        headers=analyst_headers,
    )

    note = _notes()[0]
    assert note.date == datetime(2026, 2, 3, 14, 25)
    assert note.form == {"peso": 80}


def test_update_keeps_the_date_and_form_when_they_are_null(
    client, analyst_headers, primary_care
):
    """Teste post /notes/<idNote> - Com PRIMARYCARE, data e formulário nulos não devem sobrescrever os valores atuais"""
    id_note = _create_note("texto original", form={"peso": 70})

    client.post(
        f"{NOTES_URL}/{id_note}",
        json={"text": "novo texto", "date": None, "form": None},
        headers=analyst_headers,
    )

    note = _notes()[0]
    assert note.date == datetime(2026, 1, 5, 9, 0)
    assert note.form == {"peso": 70}
