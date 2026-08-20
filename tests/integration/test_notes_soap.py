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
    """Insert the nav-soap-config global memory and a source clinical note"""
    session.execute(
        text(
            "INSERT INTO public.memoria (tipo, valor, update_at, update_by) "
            "VALUES ('nav-soap-config', CAST(:value AS json), now(), 1)"
        ),
        {"value": '{"prompt": "test soap prompt", "model_id": "test-model-id"}'},
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
    session.execute(text("DELETE FROM public.memoria WHERE tipo = 'nav-soap-config'"))
    session_commit()


@pytest.fixture
def soap_v2_test_data():
    """Insert legacy + multi-prompt (v2) soap configs and a source clinical note"""
    session.execute(
        text(
            "INSERT INTO public.memoria (tipo, valor, update_at, update_by) "
            "VALUES ('nav-soap-config', CAST(:value AS json), now(), 1)"
        ),
        {"value": '{"prompt": "legacy prompt", "model_id": "test-model-id"}'},
    )
    session.execute(
        text(
            "INSERT INTO public.memoria (tipo, valor, update_at, update_by) "
            "VALUES ('nav-soap-config-v2', CAST(:value AS json), now(), 1)"
        ),
        {
            "value": '{"model_id": "test-model-id", "default_key": "guide", '
            '"prompts": ['
            '{"key": "guide", "label": "Novo formato", "prompt": "guide prompt"}, '
            '{"key": "classic", "label": "Padrão", "prompt": "classic prompt"}'
            "]}"
        },
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
    session.execute(
        text(
            "DELETE FROM public.memoria "
            "WHERE tipo IN ('nav-soap-config', 'nav-soap-config-v2')"
        )
    )
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
    data = response.get_json()["data"]
    assert data["text"] == FAKE_SOAP_TEXT
    # legacy single-prompt config: no variant used and no options exposed
    assert data["prompt_key"] is None
    assert data["prompt_options"] == []
    assert captured["system"] == "test soap prompt"
    # the note's form answers and text must be part of the LLM input
    assert "AVCi" in captured["messages"][0]["content"]
    assert "Pré-Consulta de teste" in captured["messages"][0]["content"]


def test_generate_soap_v2_default_prompt(
    client, navigator_headers, soap_v2_test_data, monkeypatch
):
    """POST /notes/soap — v2 config takes precedence and uses the default variant"""
    captured = {}

    def fake_prompt(messages, system, config):
        captured["system"] = system
        captured["config"] = config
        return FAKE_SOAP_TEXT

    monkeypatch.setattr(soap_service, "_prompt_soap", fake_prompt)

    response = client.post(URL, json={"id": SOAP_NOTE_ID}, headers=navigator_headers)

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["text"] == FAKE_SOAP_TEXT
    assert data["prompt_key"] == "guide"
    assert data["prompt_options"] == [
        {"key": "guide", "label": "Novo formato"},
        {"key": "classic", "label": "Padrão"},
    ]
    assert captured["system"] == "guide prompt"
    assert captured["config"]["model_id"] == "test-model-id"


def test_generate_soap_v2_selected_prompt(
    client, navigator_headers, soap_v2_test_data, monkeypatch
):
    """POST /notes/soap — an explicit prompt_key selects that variant"""
    captured = {}

    def fake_prompt(messages, system, config):
        captured["system"] = system
        return FAKE_SOAP_TEXT

    monkeypatch.setattr(soap_service, "_prompt_soap", fake_prompt)

    response = client.post(
        URL,
        json={"id": SOAP_NOTE_ID, "prompt_key": "classic"},
        headers=navigator_headers,
    )

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["prompt_key"] == "classic"
    assert captured["system"] == "classic prompt"


def test_generate_soap_v2_unknown_prompt_key(
    client, navigator_headers, soap_v2_test_data
):
    """POST /notes/soap — returns 400 for a prompt_key not present in the config"""
    response = client.post(
        URL,
        json={"id": SOAP_NOTE_ID, "prompt_key": "does-not-exist"},
        headers=navigator_headers,
    )

    assert response.status_code == 400


def test_generate_soap_missing_config(client, navigator_headers):
    """POST /notes/soap — returns 500 when the soap-config memory record is missing"""
    response = client.post(URL, json={"id": SOAP_NOTE_ID}, headers=navigator_headers)

    assert response.status_code == 500


def test_create_note_as_navigator(client, navigator_headers):
    """POST /notes — returns 401 for navigators (READ_NAV does not allow note creation)"""
    payload = {
        "admissionNumber": ADMISSION_NUMBER,
        "notes": "Evolução SOAP de teste",
        "tplName": "Evolução Farmacêutica - Teleconsulta",
    }

    response = client.post("/notes", json=payload, headers=navigator_headers)

    assert response.status_code == 401


def test_create_note_permission_denied(client, viewer_headers):
    """POST /notes — returns 401 for users without WRITE_PRESCRIPTION or READ_NAV"""
    payload = {
        "admissionNumber": ADMISSION_NUMBER,
        "notes": "não autorizado",
    }

    response = client.post("/notes", json=payload, headers=viewer_headers)

    assert response.status_code == 401
