"""Integration tests for ``POST /support/create-ticket``.

Opening a ticket is a single request that fans out into several Odoo writes, and
only the "Tipo de chamado" field of that fan-out was covered so far
(``test_support_ticket_type``). The rest of the contract is what these tests pin
down, because every piece of it is invisible to the caller and only observable in
the payloads sent upstream:

* **who the ticket belongs to** — a user already known to Odoo is attached by
  ``partner_id``; an unknown one has to travel as ``partner_name`` /
  ``partner_email`` instead, or the ticket lands with no requester at all;
* **the uploaded files** — each one becomes an ``ir.attachment`` filed against
  the ticket that was just created (a wrong ``res_id`` silently attaches the
  print screen to someone else's ticket) and then has to be linked to the
  message, or the records stay orphaned and the support team never sees them;
* **the message thread** — the description is posted as a message authored by the
  ticket's own partner, and the NZero answer and question summary each add their
  own comment, so the agent picking the ticket up reads what the user was already
  told;
* **the degraded paths** — Odoo unreachable, and Odoo reachable but saving
  nothing. Both have to surface as a 504, not as a 500 or a crash.

Odoo is reached over XML-RPC and is unreachable from a test, so
``support_service._get_client`` is replaced by a stub that records every call.
"""

import base64
import io

import pytest

from models.main import User
from security.role import Role
from tests.conftest import get_access, make_headers, session
from services import support_service
from utils import status

CREATE_URL = "/support/create-ticket"

# the ticket id Odoo hands back from web_save, and the partner behind it
_TICKET_ID = 4242
_PARTNER_ID = 7
# ids the stub returns for the created ir.attachment records
_ATTACHMENT_IDS = [901, 902, 903]

# tells "not given" apart from an explicit empty/None answer from Odoo
_DEFAULT = object()


class _Odoo:
    """Stub of the Odoo execute callable that records every call it receives.

    ``partner`` is what ``res.partner.search_read`` answers (an empty list means
    the user is unknown to Odoo), ``saved`` what ``helpdesk.ticket.web_save``
    returns and ``ticket`` what the follow-up ``search_read`` returns.
    """

    def __init__(self, partner=_DEFAULT, saved=_DEFAULT, ticket=_DEFAULT):
        self.partner = (
            [{"id": _PARTNER_ID, "name": "Fulano Beltrano", "parent_id": False}]
            if partner is _DEFAULT
            else partner
        )
        self.saved = [{"id": _TICKET_ID}] if saved is _DEFAULT else saved
        self.ticket = (
            [
                {
                    "id": _TICKET_ID,
                    "access_token": "tok",
                    "ticket_ref": "REF-1",
                    "partner_id": [_PARTNER_ID, "Fulano Beltrano"],
                }
            ]
            if ticket is _DEFAULT
            else ticket
        )
        self.calls = []
        self._attachments = list(_ATTACHMENT_IDS)

    def __call__(self, model, action, payload, options):
        self.calls.append(
            {"model": model, "action": action, "payload": payload, "options": options}
        )

        if model == "res.partner" and action == "search_read":
            return self.partner

        if model == "helpdesk.ticket" and action == "web_save":
            return self.saved

        if model == "ir.attachment" and action == "create":
            return self._attachments.pop(0)

        if model == "helpdesk.ticket" and action == "search_read":
            return self.ticket

        return None

    def find(self, model, action):
        """Every recorded call to ``model``/``action``, in the order they ran."""
        return [c for c in self.calls if c["model"] == model and c["action"] == action]

    def payload_of(self, model, action):
        """The payload of the first call to ``model``/``action``, as sent."""
        return self.find(model, action)[0]["payload"]

    def ticket_sent(self):
        """The ticket dict given to ``helpdesk.ticket.web_save``."""
        return self.payload_of("helpdesk.ticket", "web_save")[1]

    def first(self, model, action):
        """The first argument of the first call to ``model``/``action``."""
        return self.payload_of(model, action)[0]


@pytest.fixture
def odoo(monkeypatch):
    """Install the default stub and hand it back for the assertions."""
    stub = _Odoo()
    monkeypatch.setattr(support_service, "_get_client", lambda: stub)

    return stub


@pytest.fixture
def requester_headers(client):
    """Headers of a SUPPORT_REQUESTER — the role that opens tickets."""
    return make_headers(get_access(client, roles=[Role.SUPPORT_REQUESTER.value]))


def _post(client, headers, files=None, **fields):
    """Post the multipart form the support modal sends."""
    data = {
        "fromUrl": "http://localhost:3000/",
        "category": "Erro",
        "title": "Assunto",
        "description": "Mensagem",
        **fields,
    }

    if files:
        data["fileList[]"] = files

    return client.post(
        CREATE_URL, data=data, headers=headers, content_type="multipart/form-data"
    )


def _upload(name, content):
    """A file as Werkzeug's test client expects it in a multipart field."""
    return (io.BytesIO(content), name)


def _demo_user():
    """The seeded user the requester fixture authenticates as."""
    return session.query(User).filter(User.email == "demo").first()


# --- the ticket requester ---


def test_ticket_is_filed_against_the_known_partner(client, requester_headers, odoo):
    """A user Odoo already knows is attached by id, not by name and e-mail."""
    response = _post(client, requester_headers)

    assert response.status_code == status.HTTP_200_OK

    ticket = odoo.ticket_sent()
    assert ticket["partner_id"] == _PARTNER_ID
    assert "partner_name" not in ticket
    assert "partner_email" not in ticket


def test_the_partner_is_looked_up_by_the_caller_email(client, requester_headers, odoo):
    """The partner search runs on the e-mail of the authenticated user."""
    response = _post(client, requester_headers)

    assert response.status_code == status.HTTP_200_OK

    lookup = odoo.first("res.partner", "search_read")
    assert lookup == [["email", "=", _demo_user().email]]


def test_an_unknown_requester_travels_as_name_and_email(client, requester_headers):
    """With no partner record the ticket carries the identity inline [no partner_id]."""
    stub = _Odoo(partner=[])
    user = _demo_user()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(support_service, "_get_client", lambda: stub)
        response = _post(client, requester_headers)

    assert response.status_code == status.HTTP_200_OK

    ticket = stub.ticket_sent()
    assert "partner_id" not in ticket
    assert ticket["partner_name"] == user.name
    assert ticket["partner_email"] == user.email


def test_the_ticket_records_the_caller_schema_and_origin(
    client, requester_headers, odoo
):
    """The ticket carries the tenant and the page the user came from."""
    response = _post(client, requester_headers, fromUrl="http://localhost:3000/exames")

    assert response.status_code == status.HTTP_200_OK

    ticket = odoo.ticket_sent()
    assert ticket["x_studio_schema_1"] == "demo"
    assert ticket["x_studio_fromurl"] == "http://localhost:3000/exames"
    assert ticket["description"] == "Mensagem"


# --- attachments ---


def test_each_uploaded_file_becomes_an_attachment(client, requester_headers, odoo):
    """One ir.attachment per file, filed against the ticket that was just created."""
    response = _post(
        client,
        requester_headers,
        files=[_upload("print1.png", b"one"), _upload("print2.png", b"two")],
    )

    assert response.status_code == status.HTTP_200_OK

    uploads = [c["payload"][0] for c in odoo.find("ir.attachment", "create")]
    assert [u["name"] for u in uploads] == ["print1.png", "print2.png"]

    for upload in uploads:
        assert upload["res_model"] == "helpdesk.ticket"
        assert upload["res_id"] == _TICKET_ID
        assert upload["type"] == "binary"


def test_the_file_content_is_sent_base64_encoded(client, requester_headers, odoo):
    """Odoo 19 reads the bytes from ``raw``, as a base64 string."""
    response = _post(client, requester_headers, files=[_upload("print.png", b"bytes")])

    assert response.status_code == status.HTTP_200_OK

    upload = odoo.first("ir.attachment", "create")
    assert upload["raw"] == base64.b64encode(b"bytes").decode("ascii")


def test_the_attachments_are_linked_to_the_message(client, requester_headers, odoo):
    """Unlinked attachments stay orphaned, so the ids ride on the message."""
    response = _post(
        client,
        requester_headers,
        files=[_upload("a.png", b"a"), _upload("b.png", b"b")],
    )

    assert response.status_code == status.HTTP_200_OK

    message = odoo.first("mail.message", "create")
    assert message["attachment_ids"] == _ATTACHMENT_IDS[:2]


def test_a_ticket_without_files_uploads_nothing(client, requester_headers, odoo):
    """No file in the form means no ir.attachment call at all."""
    response = _post(client, requester_headers)

    assert response.status_code == status.HTTP_200_OK
    assert odoo.find("ir.attachment", "create") == []
    assert odoo.first("mail.message", "create")["attachment_ids"] == []


# --- the message thread ---


def test_the_description_is_posted_as_a_message_from_the_partner(
    client, requester_headers, odoo
):
    """The ticket body is repeated as a message authored by the ticket's partner."""
    response = _post(client, requester_headers, description="Não consigo checar")

    assert response.status_code == status.HTTP_200_OK

    message = odoo.first("mail.message", "create")
    assert message["message_type"] == "email"
    assert message["author_id"] == _PARTNER_ID
    assert message["body"] == "Não consigo checar"
    assert message["model"] == "helpdesk.ticket"
    assert message["res_id"] == _TICKET_ID
    assert message["subtype_id"] == 1


def test_no_message_is_posted_when_the_ticket_has_no_partner(client, requester_headers):
    """Without a partner there is no author, so the message is skipped."""
    stub = _Odoo(ticket=[{"id": _TICKET_ID, "access_token": "tok"}])

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(support_service, "_get_client", lambda: stub)
        response = _post(client, requester_headers)

    assert response.status_code == status.HTTP_200_OK
    assert stub.find("mail.message", "create") == []


def test_the_nzero_answer_is_posted_as_a_comment(client, requester_headers, odoo):
    """What NZero already answered is added to the thread for the agent to read."""
    response = _post(client, requester_headers, nzero_response="Já respondido pelo N0")

    assert response.status_code == status.HTTP_200_OK

    messages = [c["payload"][0] for c in odoo.find("mail.message", "create")]
    comments = [m for m in messages if m["message_type"] == "comment"]

    assert len(comments) == 1
    assert comments[0]["body"] == "Já respondido pelo N0"
    assert comments[0]["model"] == "helpdesk.ticket"
    assert comments[0]["res_id"] == _TICKET_ID
    assert comments[0]["subtype_id"] == 2


def test_the_nzero_summary_is_posted_as_a_comment(client, requester_headers, odoo):
    """The question summary is a comment of its own, independent of the answer."""
    response = _post(client, requester_headers, nzero_summary="Resumo da dúvida")

    assert response.status_code == status.HTTP_200_OK

    messages = [c["payload"][0] for c in odoo.find("mail.message", "create")]
    comments = [m for m in messages if m["message_type"] == "comment"]

    assert len(comments) == 1
    assert comments[0]["body"] == "Resumo da dúvida"
    assert comments[0]["subtype_id"] == 2


def test_both_nzero_messages_are_posted_answer_first(client, requester_headers, odoo):
    """Answer and summary are two comments, in that order."""
    response = _post(
        client,
        requester_headers,
        nzero_response="Resposta",
        nzero_summary="Resumo",
    )

    assert response.status_code == status.HTTP_200_OK

    messages = [c["payload"][0] for c in odoo.find("mail.message", "create")]
    comments = [m for m in messages if m["message_type"] == "comment"]

    assert [c["body"] for c in comments] == ["Resposta", "Resumo"]


def test_a_plain_ticket_posts_no_comment(client, requester_headers, odoo):
    """Without NZero fields the thread holds the description message only."""
    response = _post(client, requester_headers)

    assert response.status_code == status.HTTP_200_OK

    messages = [c["payload"][0] for c in odoo.find("mail.message", "create")]
    assert [m["message_type"] for m in messages] == ["email"]


# --- what the caller gets back ---


def test_the_saved_ticket_is_returned_to_the_caller(client, requester_headers, odoo):
    """The response carries the re-read ticket, which is what builds the portal link."""
    response = _post(client, requester_headers)

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"] == odoo.ticket


# --- degraded paths ---


def test_an_unreachable_odoo_is_a_gateway_timeout(
    client, requester_headers, monkeypatch
):
    """A timeout on authentication yields no client, and must not become a 500."""
    monkeypatch.setattr(support_service, "_get_client", lambda: None)

    response = _post(client, requester_headers)

    assert response.status_code == status.HTTP_504_GATEWAY_TIMEOUT


def test_a_ticket_odoo_did_not_save_is_a_gateway_timeout(client, requester_headers):
    """web_save answering nothing leaves no ticket id to work with [504]."""
    stub = _Odoo(saved=None)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(support_service, "_get_client", lambda: stub)
        response = _post(client, requester_headers)

    assert response.status_code == status.HTTP_504_GATEWAY_TIMEOUT
    assert stub.find("ir.attachment", "create") == []
    assert stub.find("mail.message", "create") == []


# --- permission ---


def test_creating_a_ticket_requires_the_write_support_permission(
    client, viewer_headers, odoo
):
    """A VIEWER holds READ_SUPPORT only and may not open a ticket [401]."""
    response = _post(client, viewer_headers)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert odoo.calls == []
