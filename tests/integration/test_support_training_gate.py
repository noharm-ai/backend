"""Integration tests for the mandatory-training gate on ticket creation.

A user who still owes mandatory training cannot open a support ticket; holders of
ADMIN_SUPPORT may override it for an urgent ticket, and the override is recorded
in the ticket body.

``create_ticket`` talks to Odoo over XML-RPC, so tests that need to get *past*
the gate stub ``support_service._get_client`` and inspect what the ticket payload
would have been. The gate itself runs before any client call, so the blocked
cases need no stubbing.
"""

import pytest
from sqlalchemy import text

from config import Config
from security.permission import Permission
from security.role import Role
from services import support_service
from tests.conftest import get_access, make_headers, session, session_commit

TRAINING_ID = 991001
ITEM_ID = 991001
DEMO_USER_ID = 1


def _add_mandatory_training():
    """One globally mandatory module with a single unfinished lesson."""
    session.execute(
        text(
            "INSERT INTO public.treinamento "
            "(idtreinamento, pagina, titulo, resumo, posicao, ativo, obrigatorio, "
            "escopo, audiencia, tempo_horas, created_at, created_by) "
            "VALUES (:id, :pagina, 'Gate', 'Gate', 80, true, true, "
            "'global', 'all', 0, now(), :uid)"
        ),
        {"id": TRAINING_ID, "pagina": ["gate"], "uid": DEMO_USER_ID},
    )
    session.execute(
        text(
            "INSERT INTO public.treinamento_item "
            "(idtreinamento_item, idtreinamento, titulo, texto, posicao, ativo, "
            "created_at, created_by) "
            "VALUES (:item, :id, 'Lesson', 'Text', 1, true, now(), :uid)"
        ),
        {"item": ITEM_ID, "id": TRAINING_ID, "uid": DEMO_USER_ID},
    )
    session_commit()


def _finish_the_training():
    """Record the lesson and the module as finished for the demo user."""
    session.execute(
        text(
            "INSERT INTO public.treinamento_item_usuario "
            "(idtreinamento_item, idusuario, created_at) VALUES (:item, :uid, now())"
        ),
        {"item": ITEM_ID, "uid": DEMO_USER_ID},
    )
    session.execute(
        text(
            "INSERT INTO public.treinamento_usuario "
            "(idtreinamento, idusuario, created_at) VALUES (:id, :uid, now())"
        ),
        {"id": TRAINING_ID, "uid": DEMO_USER_ID},
    )
    session_commit()


def _cleanup():
    for statement in (
        "DELETE FROM public.treinamento_item_usuario WHERE idtreinamento_item = :item",
        "DELETE FROM public.treinamento_usuario WHERE idtreinamento = :id",
        "DELETE FROM public.treinamento_item WHERE idtreinamento_item = :item",
        "DELETE FROM public.treinamento WHERE idtreinamento = :id",
    ):
        session.execute(text(statement), {"id": TRAINING_ID, "item": ITEM_ID})
    session_commit()


@pytest.fixture(autouse=True)
def mandatory_training(monkeypatch):
    """A pending mandatory module, with obligations enabled."""
    monkeypatch.setattr(Config, "FEATURE_USER_ONBOARDING", True)
    _cleanup()
    _add_mandatory_training()
    yield
    _cleanup()


@pytest.fixture
def odoo_stub(monkeypatch):
    """Replace the Odoo client and capture the ticket payload it is given."""
    saved = {}

    def _client(model, action, payload, options):
        if model == "res.partner":
            return [{"id": 7, "name": "Demo", "parent_id": False}]

        if model == "helpdesk.ticket" and action == "web_save":
            saved["ticket"] = payload[1]
            return [{"id": 4242}]

        if model == "helpdesk.ticket" and action == "search_read":
            return [{"id": 4242, "access_token": "tok", "ticket_ref": "REF-1"}]

        return None

    monkeypatch.setattr(support_service, "_get_client", lambda: _client)

    return saved


def _post_ticket(client, headers, urgent=None):
    data = {
        "fromUrl": "http://localhost:3000/",
        "category": "Erro",
        "title": "Assunto",
        "description": "Mensagem",
    }

    if urgent is not None:
        data["urgent"] = urgent

    return client.post(
        "/support/create-ticket",
        data=data,
        headers=headers,
        content_type="multipart/form-data",
    )


def _headers(client, roles):
    return make_headers(get_access(client, roles=roles))


# SUPPORT_REQUESTER can open tickets and reach the training, and holds no
# ADMIN_SUPPORT: the plain "must finish the training first" case.
GATED_ROLES = [Role.SUPPORT_REQUESTER.value]


# --- blocked ---


def test_pending_training_blocks_ticket_creation(client):
    """A user without ADMIN_SUPPORT is refused before Odoo is even contacted."""
    headers = _headers(client, GATED_ROLES)

    response = _post_ticket(client, headers)

    assert response.status_code == 400
    assert response.get_json()["code"] == "errors.pendingMandatoryTraining"


def test_urgent_alone_does_not_bypass_the_block(client):
    """Marking a ticket urgent is not enough without ADMIN_SUPPORT."""
    headers = _headers(client, GATED_ROLES)

    response = _post_ticket(client, headers, urgent="true")

    assert response.status_code == 400
    assert response.get_json()["code"] == "errors.pendingMandatoryTraining"


def test_admin_support_alone_does_not_bypass_the_block(client):
    """ADMIN_SUPPORT is not a standing exemption: the ticket must be urgent."""
    headers = _headers(client, [Role.ADMIN.value])

    response = _post_ticket(client, headers)

    assert response.status_code == 400
    assert response.get_json()["code"] == "errors.pendingMandatoryTraining"


# --- allowed ---


def test_admin_support_bypasses_for_an_urgent_ticket(client, odoo_stub):
    """ADMIN_SUPPORT + urgent gets through, and the ticket records why."""
    headers = _headers(client, [Role.ADMIN.value])

    response = _post_ticket(client, headers, urgent="true")

    assert response.status_code == 200

    description = odoo_stub["ticket"]["description"]
    assert "Chamado urgente" in description
    assert "bypass ADMIN_SUPPORT" in description
    # the user's own message is preserved
    assert "Mensagem" in description


def test_finished_training_creates_a_normal_ticket(client, odoo_stub):
    """With no pending training the gate is transparent and adds no note."""
    _finish_the_training()
    headers = _headers(client, GATED_ROLES)

    response = _post_ticket(client, headers)

    assert response.status_code == 200
    assert "Chamado urgente" not in odoo_stub["ticket"]["description"]


def test_feature_flag_off_disables_the_gate(client, monkeypatch, odoo_stub):
    """The env flag gates obligations, so with it off nobody is blocked."""
    monkeypatch.setattr(Config, "FEATURE_USER_ONBOARDING", False)
    headers = _headers(client, GATED_ROLES)

    response = _post_ticket(client, headers)

    assert response.status_code == 200
    assert "Chamado urgente" not in odoo_stub["ticket"]["description"]


def test_support_manager_bypasses_for_an_urgent_ticket(client, odoo_stub):
    """The realistic bypass holder: SUPPORT_MANAGER, not just ADMIN."""
    headers = _headers(client, [Role.SUPPORT_MANAGER.value])

    response = _post_ticket(client, headers, urgent="true")

    assert response.status_code == 200
    assert "bypass ADMIN_SUPPORT" in odoo_stub["ticket"]["description"]


# --- the "cannot comply" safety net ---


@pytest.mark.parametrize(
    "role", [Role.SUPPORT_REQUESTER.value, Role.SUPPORT_MANAGER.value]
)
def test_every_ticket_role_can_reach_the_training(client, role):
    """The gate is only fair if the blocked user can actually do something about
    it, so every role that can open a ticket must be able to list the training."""
    headers = _headers(client, [role])

    assert client.get("/training/list", headers=headers).status_code == 200


def test_a_role_without_training_access_is_not_blocked():
    """Defence in depth: no shipped role hits this today (every WRITE_SUPPORT
    role can reach the training), but a future one added without
    READ_BASIC_FEATURES must not be locked out of tickets with no way to comply.
    Called directly, since no role combination can express it any more."""

    class _Ctx:
        id = DEMO_USER_ID
        schema = "demo"

    assert (
        support_service._check_mandatory_training(
            user_context=_Ctx(),
            user_permissions=[Permission.WRITE_SUPPORT],
            urgent=False,
        )
        is False
    )
