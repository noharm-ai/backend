import pytest
from sqlalchemy import text

from services import soap_service
from tests.conftest import session, session_commit

URL = "/notes/soap"
SOAP_NOTE_ID = 100901  # test-generated ids use >= 100000
ADMISSION_NUMBER = 5
FAKE_SOAP_TEXT = "EVOLUÇÃO FARMACÊUTICA - Teleconsulta NoHarm\n\n(S)\n\nTeste"


@pytest.fixture
def soap_test_data():
    """Insert the soap-config global memory and a source clinical note"""
    session.execute(
        text(
            "INSERT INTO public.memoria (tipo, valor, update_at, update_by) "
            "VALUES ('soap-config', CAST(:value AS json), now(), 1)"
        ),
        {"value": '{"prompt": "test soap prompt"}'},
    )
    session.execute(
        text(
            "INSERT INTO demo.evolucao "
            "(fkevolucao, nratendimento, texto, dtevolucao, cargo, exame, formulario) "
            "VALUES (:id, :admission, 'Pré-Consulta de teste', now(), "
            "'Farmacêutica', false, CAST(:form AS json))"
        ),
        {
            "id": SOAP_NOTE_ID,
            "admission": ADMISSION_NUMBER,
            "form": '{"pre-consulta": {"condicao": "AVCi"}}',
        },
    )
    session_commit()
    yield
    session.execute(
        text("DELETE FROM demo.evolucao WHERE fkevolucao = :id"),
        {"id": SOAP_NOTE_ID},
    )
    session.execute(text("DELETE FROM public.memoria WHERE tipo = 'soap-config'"))
    session_commit()


def test_generate_soap_no_token(client):
    """POST /notes/soap — returns 401 without authentication"""
    response = client.post(
        URL, json={"id": SOAP_NOTE_ID}, headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 401


def test_generate_soap_permission_denied(client, viewer_headers):
    """POST /notes/soap — returns 401 for users without READ_NAV permission"""
    response = client.post(URL, json={"id": SOAP_NOTE_ID}, headers=viewer_headers)

    assert response.status_code == 401


def test_generate_soap_invalid_note(client, navigator_headers, soap_test_data):
    """POST /notes/soap — returns 400 when the clinical note does not exist"""
    response = client.post(URL, json={"id": 999999999}, headers=navigator_headers)

    assert response.status_code == 400


def test_generate_soap(client, navigator_headers, soap_test_data, monkeypatch):
    """POST /notes/soap — generates SOAP text from a clinical note (LLM mocked)"""
    captured = {}

    def fake_prompt(messages, system, config):
        captured["messages"] = messages
        captured["system"] = system
        return FAKE_SOAP_TEXT

    monkeypatch.setattr(soap_service, "_prompt_soap", fake_prompt)

    response = client.post(URL, json={"id": SOAP_NOTE_ID}, headers=navigator_headers)

    assert response.status_code == 200
    assert response.get_json()["data"]["text"] == FAKE_SOAP_TEXT
    assert captured["system"] == "test soap prompt"
    # the note's form answers and text must be part of the LLM input
    assert "AVCi" in captured["messages"][0]["content"]
    assert "Pré-Consulta de teste" in captured["messages"][0]["content"]


def test_generate_soap_missing_config(client, navigator_headers):
    """POST /notes/soap — returns 500 when the soap-config memory record is missing"""
    response = client.post(URL, json={"id": SOAP_NOTE_ID}, headers=navigator_headers)

    assert response.status_code == 500


def test_create_note_as_navigator(client, navigator_headers):
    """POST /notes — navigators (READ_NAV) can create notes without the PRIMARYCARE feature"""
    payload = {
        "admissionNumber": ADMISSION_NUMBER,
        "notes": "Evolução SOAP de teste",
        "tplName": "Evolução Farmacêutica - Teleconsulta",
    }

    response = client.post("/notes", json=payload, headers=navigator_headers)

    assert response.status_code == 200
    created_id = response.get_json()["data"]

    result = session.execute(
        text(
            "SELECT texto, cargo FROM demo.evolucao WHERE fkevolucao = :id"
        ),
        {"id": created_id},
    ).fetchone()

    assert result is not None
    assert result[0] == payload["notes"]
    assert result[1] == payload["tplName"]

    session.execute(
        text("DELETE FROM demo.evolucao WHERE fkevolucao = :id"), {"id": created_id}
    )
    session_commit()


def test_create_note_permission_denied(client, viewer_headers):
    """POST /notes — returns 401 for users without WRITE_PRESCRIPTION or READ_NAV"""
    payload = {
        "admissionNumber": ADMISSION_NUMBER,
        "notes": "não autorizado",
    }

    response = client.post("/notes", json=payload, headers=viewer_headers)

    assert response.status_code == 401
