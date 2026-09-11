"""Integration tests for the two support write endpoints that were uncovered.

* ``POST /support/attachment`` — the "send me the print screen" step. A user who
  already has a ticket uploads files to it, and the backend has to turn each one
  into an Odoo ``ir.attachment`` and then post a ``mail.message`` on the ticket
  so the attachments actually show up in the thread instead of being orphaned
  records. The grouping matters: one message per form field, carrying every file
  sent under it, authored by the ticket's own partner.
* ``POST /support/create-closed-ticket`` — what NZero calls when it answered the
  question itself. The ticket is opened and closed in the same request, so the
  stage and team it lands in are the whole contract.

Odoo is reached over XML-RPC and is unreachable from a test, so
``support_service._get_client`` is replaced by a stub that records every query.
That makes the two things worth asserting testable: the *payloads* sent upstream
(a wrong ``res_id`` files the attachment against another ticket) and the
degraded path when Odoo times out — the client is ``None`` then, and the caller
must get a 504 instead of a 500.
"""

import base64
import io
import json

import pytest

from security.role import Role
from services import support_service
from tests.conftest import get_access, make_headers
from utils import status

ATTACHMENT_URL = "/support/attachment"
CLOSED_TICKET_URL = "/support/create-closed-ticket"

# the ticket the uploads are filed against, as the form sends it: a string
_TICKET_ID = "4242"
# the res.partner behind that ticket, which authors the attachment message
_PARTNER_ID = 7
# ids the stub hands back for the created ir.attachment records
_ATTACHMENT_IDS = [901, 902, 903, 904]
# id the stub hands back for a created helpdesk.ticket
_NEW_TICKET_ID = 5150

# the demo user these tests authenticate as
DEMO_SCHEMA = "demo"

# SUPPORT_REQUESTER is the smallest role holding WRITE_SUPPORT.
REQUESTER_ROLES = [Role.SUPPORT_REQUESTER.value]


class OdooStub:
    """A stand-in Odoo client that records every query and answers from a script.

    ``support_service`` calls the object returned by ``_get_client`` as
    ``client(model=..., action=..., payload=..., options=...)``, so the stub is
    callable. ``ticket`` is what the helpdesk.ticket lookup answers and
    ``ir.attachment`` creations hand back one id each, in order.
    """

    def __init__(self, ticket=None, new_ticket=None):
        self.ticket = (
            ticket
            if ticket is not None
            else [
                {
                    "id": int(_TICKET_ID),
                    "access_token": "tok",
                    "ticket_ref": "REF-1",
                    "partner_id": [_PARTNER_ID, "Fulano Beltrano"],
                }
            ]
        )
        self.new_ticket = (
            new_ticket if new_ticket is not None else [{"id": _NEW_TICKET_ID}]
        )
        self.attachment_ids = list(_ATTACHMENT_IDS)
        self.calls = []

    def __call__(self, model, action, payload, options):
        self.calls.append(
            {"model": model, "action": action, "payload": payload, "options": options}
        )

        if model == "helpdesk.ticket":
            return self.new_ticket if action == "web_save" else self.ticket

        if model == "ir.attachment":
            return self.attachment_ids.pop(0)

        return True

    def calls_for(self, model: str, action: str = None) -> list:
        """Every recorded call against a model, optionally narrowed to an action."""
        return [
            call
            for call in self.calls
            if call["model"] == model and (action is None or call["action"] == action)
        ]


@pytest.fixture
def odoo(monkeypatch):
    """Point the service at a stub instead of the real Odoo transport."""
    stub = OdooStub()
    monkeypatch.setattr(support_service, "_get_client", lambda: stub)
    return stub


@pytest.fixture
def unreachable_odoo(monkeypatch):
    """Odoo timed out: _get_client answers None."""
    monkeypatch.setattr(support_service, "_get_client", lambda: None)


@pytest.fixture
def requester_headers(client):
    """Headers for a user holding WRITE_SUPPORT."""
    return make_headers(get_access(client, roles=REQUESTER_ROLES))


def _upload(client, headers, files=None, id_ticket=_TICKET_ID):
    """POST a multipart upload to the attachment endpoint.

    ``files`` maps a form field name onto the ``(content, filename)`` pairs sent
    under it, mirroring the repeated ``fileList[]`` fields the browser produces.
    """
    data = {}

    if id_ticket is not None:
        data["id_ticket"] = id_ticket

    for field, uploads in (files or {}).items():
        data[field] = [(io.BytesIO(content), filename) for content, filename in uploads]

    return client.post(
        ATTACHMENT_URL, data=data, headers=headers, content_type="multipart/form-data"
    )


def _closed_ticket(client, headers, description="Dúvida respondida pelo NZero"):
    """POST the AI-closed ticket payload."""
    return client.post(
        CLOSED_TICKET_URL,
        data=json.dumps({"description": description}),
        headers=headers,
    )


def _data(response):
    assert response.status_code == status.HTTP_200_OK
    return response.get_json()["data"]


_ONE_FILE = {"fileList[]": [(b"imagem-de-teste", "print.png")]}


# ---------------------------------------------------------------------------
# /support/attachment: guards
# ---------------------------------------------------------------------------


def test_attachment_requires_a_ticket_id(client, requester_headers, odoo):
    """POST attachment - an upload naming no ticket is refused before Odoo is
    contacted [400 BAD REQUEST]"""
    response = _upload(client, requester_headers, _ONE_FILE, id_ticket=None)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.businessRules"
    assert odoo.calls == []


def test_attachment_requires_at_least_one_file(client, requester_headers, odoo):
    """POST attachment - a ticket id on its own uploads nothing, so it is refused
    [400 BAD REQUEST]"""
    response = _upload(client, requester_headers)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.businessRules"
    assert odoo.calls == []


def test_attachment_reports_an_odoo_timeout_as_a_gateway_error(
    client, requester_headers, unreachable_odoo
):
    """POST attachment - an unreachable Odoo is a gateway timeout, not a 500, so
    the upload screen can offer a retry [504 GATEWAY TIMEOUT]"""
    response = _upload(client, requester_headers, _ONE_FILE)

    assert response.status_code == status.HTTP_504_GATEWAY_TIMEOUT
    assert response.get_json()["code"] == "errors.connectionTimeout"


def test_attachment_requires_the_write_support_permission(client, viewer_headers, odoo):
    """POST attachment - a role without WRITE_SUPPORT is refused
    [401 UNAUTHORIZED]"""
    response = _upload(client, viewer_headers, _ONE_FILE)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert odoo.calls == []


# ---------------------------------------------------------------------------
# /support/attachment: what reaches Odoo
# ---------------------------------------------------------------------------


def test_attachment_looks_the_ticket_up_before_uploading(
    client, requester_headers, odoo
):
    """POST attachment - the ticket is read first, for the partner that will
    author the message and the reference the thread is keyed by"""
    _upload(client, requester_headers, _ONE_FILE)

    lookup = odoo.calls_for("helpdesk.ticket", "search_read")[0]
    # the form value is passed through as the string it arrived as
    assert lookup["payload"] == [[["id", "=", _TICKET_ID]]]
    assert lookup["options"]["limit"] == 1
    assert "partner_id" in lookup["options"]["fields"]


def test_attachment_files_the_upload_against_the_ticket(
    client, requester_headers, odoo
):
    """POST attachment - each file becomes a binary ir.attachment carrying its
    own name, base64 content and the ticket it belongs to"""
    response = _upload(client, requester_headers, _ONE_FILE)

    assert _data(response) == int(_TICKET_ID)

    created = odoo.calls_for("ir.attachment", "create")
    assert len(created) == 1

    attachment = created[0]["payload"][0]
    assert attachment["name"] == "print.png"
    assert attachment["res_model"] == "helpdesk.ticket"
    assert attachment["res_id"] == int(_TICKET_ID)
    assert attachment["type"] == "binary"
    assert attachment["raw"] == base64.b64encode(b"imagem-de-teste").decode("ascii")


def test_attachment_posts_a_message_so_the_files_show_in_the_thread(
    client, requester_headers, odoo
):
    """POST attachment - the ir.attachment records are linked from a mail.message
    authored by the ticket's partner, which is what makes them visible"""
    _upload(client, requester_headers, _ONE_FILE)

    messages = odoo.calls_for("mail.message", "create")
    assert len(messages) == 1

    message = messages[0]["payload"][0]
    assert message["author_id"] == _PARTNER_ID
    assert message["model"] == "helpdesk.ticket"
    assert message["res_id"] == int(_TICKET_ID)
    assert message["attachment_ids"] == [_ATTACHMENT_IDS[0]]
    # the field name titles the message, with the array marker stripped
    assert message["body"] == "Anexo: fileList"


def test_attachment_groups_every_file_of_one_field_into_one_message(
    client, requester_headers, odoo
):
    """POST attachment - selecting three files at once uploads three attachments
    but posts a single message linking all of them"""
    _upload(
        client,
        requester_headers,
        {
            "fileList[]": [
                (b"um", "um.png"),
                (b"dois", "dois.png"),
                (b"tres", "tres.png"),
            ]
        },
    )

    assert len(odoo.calls_for("ir.attachment", "create")) == 3

    messages = odoo.calls_for("mail.message", "create")
    assert len(messages) == 1
    assert messages[0]["payload"][0]["attachment_ids"] == _ATTACHMENT_IDS[:3]


def test_attachment_posts_one_message_per_form_field(client, requester_headers, odoo):
    """POST attachment - two different fields are two different uploads, so each
    gets its own message naming it"""
    _upload(
        client,
        requester_headers,
        {
            "fileList[]": [(b"print", "print.png")],
            "extraList[]": [(b"log", "log.txt")],
        },
    )

    messages = odoo.calls_for("mail.message", "create")
    assert len(messages) == 2

    bodies = {message["payload"][0]["body"] for message in messages}
    assert bodies == {"Anexo: fileList", "Anexo: extraList"}

    # no attachment id is linked from more than one message
    linked = [
        att_id
        for message in messages
        for att_id in message["payload"][0]["attachment_ids"]
    ]
    assert sorted(linked) == _ATTACHMENT_IDS[:2]


# ---------------------------------------------------------------------------
# /support/create-closed-ticket
# ---------------------------------------------------------------------------


def test_closed_ticket_requires_a_description(client, requester_headers, odoo):
    """POST create-closed-ticket - there is nothing to record without the answer
    text, so it is refused [400 BAD REQUEST]"""
    response = _closed_ticket(client, requester_headers, description=None)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.businessRules"
    assert odoo.calls == []


def test_closed_ticket_reports_an_odoo_timeout_as_a_gateway_error(
    client, requester_headers, unreachable_odoo
):
    """POST create-closed-ticket - an unreachable Odoo is a gateway timeout
    [504 GATEWAY TIMEOUT]"""
    response = _closed_ticket(client, requester_headers)

    assert response.status_code == status.HTTP_504_GATEWAY_TIMEOUT
    assert response.get_json()["code"] == "errors.connectionTimeout"


def test_closed_ticket_requires_the_write_support_permission(
    client, viewer_headers, odoo
):
    """POST create-closed-ticket - a role without WRITE_SUPPORT is refused
    [401 UNAUTHORIZED]"""
    response = _closed_ticket(client, viewer_headers)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert odoo.calls == []


def test_closed_ticket_opens_the_ticket_already_closed(client, requester_headers, odoo):
    """POST create-closed-ticket - NZero answered the question, so the ticket is
    filed on the support team in the closed stage and tagged as a question"""
    response = _closed_ticket(
        client, requester_headers, description="Resposta do NZero"
    )

    assert _data(response) == _NEW_TICKET_ID

    saved = odoo.calls_for("helpdesk.ticket", "web_save")
    assert len(saved) == 1

    ticket = saved[0]["payload"][1]
    assert ticket["description"] == "Resposta do NZero"
    # the schema is what routes the ticket to the right customer
    assert ticket["x_studio_schema_1"] == DEMO_SCHEMA
    assert ticket["x_studio_tipo_de_chamado"] == "Dúvida"
    assert ticket["team_id"] == 1
    assert ticket["stage_id"] == 4
    assert "NZero" in ticket["name"]


def test_closed_ticket_returns_nothing_when_odoo_saves_nothing(
    client, requester_headers, odoo
):
    """POST create-closed-ticket - Odoo answers falsy when the save produced no
    record, and the endpoint reports no id rather than raising"""
    odoo.new_ticket = False

    assert _data(_closed_ticket(client, requester_headers)) is None
