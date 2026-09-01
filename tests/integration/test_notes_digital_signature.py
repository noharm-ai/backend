import base64

import pytest
from sqlalchemy import text

from services import clinical_notes_sign_service
from tests.conftest import session, session_commit

URL = "/notes/digital-signature"
SIGN_NOTE_ID = 100902  # test-generated ids use >= 100000
ADMISSION_NUMBER = 5
SIGNER = {"signer_name": "Maria Teste", "signer_email": "maria.teste@example.com"}


@pytest.fixture
def sign_test_data():
    """Insert a clinical note and the nav-header memory used in the PDF header"""
    session.execute(
        text(
            "INSERT INTO demo.memoria (tipo, valor, update_at, update_by) "
            "VALUES ('nav-header', CAST(:value AS json), now(), 1)"
        ),
        {"value": '{"header": "<p>Instituição de Teste</p>"}'},
    )
    session.execute(
        text(
            "INSERT INTO demo.evolucao "
            "(fkevolucao, nratendimento, texto, dtevolucao, prescritor, cargo, exame) "
            "VALUES (:id, :admission, :note_text, now(), "
            "'Fulano Beltrano', 'Farmacêutica', false)"
        ),
        {
            "id": SIGN_NOTE_ID,
            "admission": ADMISSION_NUMBER,
            "note_text": "Evolução de teste<br/>para assinatura digital",
        },
    )
    session_commit()
    yield
    session.execute(
        text("DELETE FROM demo.evolucao WHERE fkevolucao = :id"),
        {"id": SIGN_NOTE_ID},
    )
    session.execute(text("DELETE FROM demo.memoria WHERE tipo = 'nav-header'"))
    session_commit()


class FakeOdooClient:
    """Records every ODOO call and returns canned responses per model/action."""

    def __init__(self):
        self.calls = []

    def __call__(self, model, action, payload, options):
        self.calls.append(
            {"model": model, "action": action, "payload": payload, "options": options}
        )

        responses = {
            ("ir.attachment", "create"): 501,
            ("sign.template", "create"): 601,
            ("sign.item.type", "search"): [11],
            ("sign.item.role", "search"): [1],
            ("sign.item", "create"): 701,
            ("res.partner", "search_read"): [],
            ("res.partner", "create"): 801,
            ("sign.send.request", "create"): 901,
            ("sign.send.request", "send_request"): True,
            ("sign.request", "search_read"): [{"id": 1001}],
            ("sign.request.item", "search_read"): [{"access_token": "tok123"}],
        }

        return responses[(model, action)]

    def find_call(self, model, action):
        """Returns the first recorded call for the given model/action."""
        for call in self.calls:
            if call["model"] == model and call["action"] == action:
                return call
        return None


def test_digital_signature_no_token(client):
    """POST /notes/digital-signature — returns 401 without authentication"""
    response = client.post(
        URL,
        json={"id": SIGN_NOTE_ID, **SIGNER},
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 401


def test_digital_signature_permission_denied(client, viewer_headers):
    """POST /notes/digital-signature — returns 401 without READ_NAV permission"""
    response = client.post(
        URL, json={"id": SIGN_NOTE_ID, **SIGNER}, headers=viewer_headers
    )

    assert response.status_code == 401


def test_digital_signature_invalid_note(client, navigator_headers):
    """POST /notes/digital-signature — returns 400 when the note does not exist"""
    response = client.post(
        URL, json={"id": 999999999, **SIGNER}, headers=navigator_headers
    )

    assert response.status_code == 400


def test_digital_signature_invalid_signer(client, navigator_headers, sign_test_data):
    """POST /notes/digital-signature — returns 400 for an invalid signer e-mail"""
    response = client.post(
        URL,
        json={
            "id": SIGN_NOTE_ID,
            "signer_name": "Maria Teste",
            "signer_email": "not-an-email",
        },
        headers=navigator_headers,
    )

    assert response.status_code == 400


def test_digital_signature(client, navigator_headers, sign_test_data, monkeypatch):
    """POST /notes/digital-signature — runs the full ODOO Sign flow (mocked)"""
    fake_client = FakeOdooClient()

    monkeypatch.setattr(
        clinical_notes_sign_service.odoo_client,
        "get_client",
        lambda context=None: fake_client,
    )

    response = client.post(
        URL, json={"id": SIGN_NOTE_ID, **SIGNER}, headers=navigator_headers
    )

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["idSignRequest"] == 1001
    assert data["link"].endswith("/sign/document/1001/tok123")
    assert data["signerEmail"] == SIGNER["signer_email"]

    # the uploaded attachment must be a valid PDF
    attachment = fake_client.find_call("ir.attachment", "create")
    pdf_bytes = base64.b64decode(attachment["payload"][0]["datas"])
    assert pdf_bytes.startswith(b"%PDF")

    # the template points to the uploaded attachment
    template = fake_client.find_call("sign.template", "create")
    assert template["payload"][0]["attachment_id"] == 501

    # the signature field is placed with fractional coordinates
    sign_item = fake_client.find_call("sign.item", "create")
    item = sign_item["payload"][0]
    assert item["template_id"] == 601
    assert 0 < item["posX"] < 1
    assert 0 < item["posY"] < 1
    assert item["page"] >= 1

    # the wizard receives the signer created as a res.partner
    partner = fake_client.find_call("res.partner", "create")
    assert partner["payload"][0]["email"] == SIGNER["signer_email"]

    wizard = fake_client.find_call("sign.send.request", "create")
    assert wizard["payload"][0]["signer_ids"][0][2]["partner_id"] == 801

    assert fake_client.find_call("sign.send.request", "send_request") is not None


def test_digital_signature_odoo_timeout(
    client, navigator_headers, sign_test_data, monkeypatch
):
    """POST /notes/digital-signature — returns 504 when ODOO is unreachable"""
    monkeypatch.setattr(
        clinical_notes_sign_service.odoo_client,
        "get_client",
        lambda context=None: None,
    )

    response = client.post(
        URL, json={"id": SIGN_NOTE_ID, **SIGNER}, headers=navigator_headers
    )

    assert response.status_code == 504
