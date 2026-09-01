"""Integration tests for the ticket-type compatibility shim on ticket creation.

The "Tipo de chamado" field is migrating from a label string bound to Odoo's
``x_studio_tipo_de_chamado`` to the Odoo type id bound to ``x_studio_tipo_chamado``.
Both have to keep working: a user's browser may still hold the previous frontend
bundle, and ``SupportFormAI`` sends labels regardless of bundle version.

``create_ticket`` talks to Odoo over XML-RPC, so ``support_service._get_client`` is
replaced by a stub that captures the ticket payload and lets the assertions look at
which field the value actually landed on.
"""

import pytest

from security.role import Role
from services import support_service
from tests.conftest import get_access, make_headers

CREATE_URL = "/support/create-ticket"

LEGACY_FIELD = "x_studio_tipo_de_chamado"
CURRENT_FIELD = "x_studio_tipo_chamado"


@pytest.fixture
def odoo_stub(monkeypatch):
    """Replace the Odoo client and capture the ticket payload it is given."""
    saved = {}

    def _client(model, action, payload, options):  # noqa: ARG001
        if model == "res.partner":
            return [{"id": 7, "name": "Fulano Beltrano", "parent_id": False}]

        if model == "helpdesk.ticket" and action == "web_save":
            saved["ticket"] = payload[1]
            return [{"id": 4242}]

        if model == "helpdesk.ticket" and action == "search_read":
            return [{"id": 4242, "access_token": "tok", "ticket_ref": "REF-1"}]

        return None

    monkeypatch.setattr(support_service, "_get_client", lambda: _client)

    return saved


def _post_ticket(client, category=None):
    data = {
        "fromUrl": "http://localhost:3000/",
        "title": "Assunto",
        "description": "Mensagem",
    }

    if category is not None:
        data["category"] = category

    return client.post(
        CREATE_URL,
        data=data,
        headers=make_headers(get_access(client, roles=[Role.SUPPORT_REQUESTER.value])),
        content_type="multipart/form-data",
    )


# --- legacy frontend: a label string ---


def test_label_goes_to_the_legacy_field(client, odoo_stub):
    """A stale bundle sends "Erro" and must keep writing the old Odoo field."""
    response = _post_ticket(client, category="Erro")

    assert response.status_code == 200

    ticket = odoo_stub["ticket"]
    assert ticket[LEGACY_FIELD] == "Erro"
    assert CURRENT_FIELD not in ticket
    assert ticket["name"] == "[Erro] Assunto"


def test_accented_label_goes_to_the_legacy_field(client, odoo_stub):
    """The labels are accented and multi-word; none of them parse as an int."""
    response = _post_ticket(client, category="Integração fora do ar")

    assert response.status_code == 200

    ticket = odoo_stub["ticket"]
    assert ticket[LEGACY_FIELD] == "Integração fora do ar"
    assert CURRENT_FIELD not in ticket
    assert ticket["name"] == "[Integração fora do ar] Assunto"


def test_missing_category_keeps_the_legacy_shape(client, odoo_stub):
    """No category at all: the old field is still present, the name says Geral."""
    response = _post_ticket(client)

    assert response.status_code == 200

    ticket = odoo_stub["ticket"]
    assert ticket[LEGACY_FIELD] is None
    assert CURRENT_FIELD not in ticket
    assert ticket["name"] == "[Geral] Assunto"


# --- current frontend: an Odoo type id ---


def test_id_goes_to_the_current_field_as_an_int(client, odoo_stub):
    """Multipart delivers "2"; Odoo needs the int, not the string."""
    response = _post_ticket(client, category="2")

    assert response.status_code == 200

    ticket = odoo_stub["ticket"]
    assert ticket[CURRENT_FIELD] == 2
    assert not isinstance(ticket[CURRENT_FIELD], str)
    assert LEGACY_FIELD not in ticket
    assert ticket["name"] == "[Erro] Assunto"


@pytest.mark.parametrize(
    ("type_id", "label"),
    [
        ("1", "Solicitação"),
        ("2", "Erro"),
        ("4", "Dúvida"),
        ("5", "Validação"),
        ("6", "Integração fora do ar"),
        ("9", "Sugestão"),
    ],
)
def test_every_option_titles_the_ticket_with_its_label(
    client, odoo_stub, type_id, label
):
    """Each id the select can send resolves to the label the ticket is titled with."""
    response = _post_ticket(client, category=type_id)

    assert response.status_code == 200

    ticket = odoo_stub["ticket"]
    assert ticket[CURRENT_FIELD] == int(type_id)
    assert ticket["name"] == f"[{label}] Assunto"


def test_unknown_id_passes_through_and_falls_back_to_geral(client, odoo_stub):
    """A type added in Odoo but not here still reaches Odoo; only the title degrades."""
    response = _post_ticket(client, category="777")

    assert response.status_code == 200

    ticket = odoo_stub["ticket"]
    assert ticket[CURRENT_FIELD] == 777
    assert LEGACY_FIELD not in ticket
    assert ticket["name"] == "[Geral] Assunto"
