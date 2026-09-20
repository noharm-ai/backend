"""Tests: POST /support/ask-n0 and POST /support/ask-n0-form

These are the HTTP face of the N0 support assistant: before a user opens a
ticket, ``/support/ask-n0`` answers the question from the knowledge base and
``/support/ask-n0-form`` turns the same question into a pre-filled ticket.

The agent itself talks to Bedrock and is covered by
``tests/unit/test_n0_agent.py``, so ``agents.n0_agent`` is stubbed here. What
these tests pin down is the service contract around it: the permission gate,
the rejection of an empty question *before* any (billed) model call, the fact
that the asking user is looked up and handed to the agent — the agent greets
them by name — and the response envelope, including the SKIP_ANSWER sentinels
being passed through verbatim so the frontend can recognise them.
"""

from unittest.mock import patch

import pytest

from security.role import Role
from services import support_service
from tests.conftest import get_access, make_headers
from utils import status

ASK_URL = "/support/ask-n0"
FORM_URL = "/support/ask-n0-form"

TICKET = {
    "type": "Erro",
    "subject": "Relatório não abre",
    "description": "O relatório consolidado não abre desde ontem.",
    "extra_fields": [{"label": "Print da tela", "type": "archive"}],
}


@pytest.fixture
def run_n0_mock():
    """Replace the N0 agent with a stub returning a fixed answer."""
    with patch.object(
        support_service.n0_agent, "run_n0", return_value="Vá em Relatórios."
    ) as mock:
        yield mock


@pytest.fixture
def run_n0_form_mock():
    """Replace the N0 form agent with a stub returning a fixed ticket."""
    with patch.object(
        support_service.n0_agent, "run_n0_form", return_value=TICKET
    ) as mock:
        yield mock


def test_ask_n0_permission_denied(client, run_n0_mock):
    """POST /support/ask-n0 - a user without READ_SUPPORT is rejected [401]"""
    headers = make_headers(get_access(client, roles=[Role.DISPENSING_MANAGER.value]))

    response = client.post(ASK_URL, json={"question": "pergunta"}, headers=headers)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    run_n0_mock.assert_not_called()


def test_ask_n0_requires_a_question(client, analyst_headers, run_n0_mock):
    """POST /support/ask-n0 - an empty question is rejected before the model call"""
    response = client.post(ASK_URL, json={"question": ""}, headers=analyst_headers)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.businessRules"
    run_n0_mock.assert_not_called()


def test_ask_n0_requires_the_question_field(client, analyst_headers, run_n0_mock):
    """POST /support/ask-n0 - a body without the question field is rejected [400]"""
    response = client.post(ASK_URL, json={}, headers=analyst_headers)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    run_n0_mock.assert_not_called()


def test_ask_n0_sends_the_question_and_the_asking_user(
    client, analyst_headers, run_n0_mock
):
    """POST /support/ask-n0 - the agent receives the question and the logged user"""
    # the user row is read inside the request; the session is closed before the
    # assertions run, so capture what matters while the instance is still bound
    seen = {}

    def _capture(query, user):
        seen["query"] = query
        seen["id"] = user.id
        seen["name"] = user.name

        return "Vá em Relatórios."

    run_n0_mock.side_effect = _capture

    response = client.post(
        ASK_URL, json={"question": "como emito o relatório?"}, headers=analyst_headers
    )

    assert response.status_code == status.HTTP_200_OK
    assert seen["query"] == "como emito o relatório?"
    # the agent addresses the user by name, so a real user row must be resolved
    assert seen["id"] is not None
    assert seen["name"]


def test_ask_n0_returns_the_answer(client, analyst_headers, run_n0_mock):
    """POST /support/ask-n0 - the agent answer comes back under 'agent'"""
    response = client.post(
        ASK_URL, json={"question": "pergunta"}, headers=analyst_headers
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"] == {"agent": "Vá em Relatórios."}


def test_ask_n0_serializes_a_non_string_answer(client, analyst_headers, run_n0_mock):
    """POST /support/ask-n0 - the agent result is stringified for the response"""

    class _AgentResult:
        def __str__(self):
            return "resposta do agente"

    run_n0_mock.return_value = _AgentResult()

    response = client.post(
        ASK_URL, json={"question": "pergunta"}, headers=analyst_headers
    )

    assert response.get_json()["data"] == {"agent": "resposta do agente"}


@pytest.mark.parametrize(
    "sentinel", ["SKIP_ANSWER DUE_TO_GUARDRAIL", "SKIP_ANSWER DUE_TO_TIMEOUT"]
)
def test_ask_n0_passes_the_skip_sentinels_through(
    client, analyst_headers, run_n0_mock, sentinel
):
    """POST /support/ask-n0 - a skipped answer is relayed verbatim [200]"""
    run_n0_mock.return_value = sentinel

    response = client.post(
        ASK_URL, json={"question": "pergunta"}, headers=analyst_headers
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"] == {"agent": sentinel}


def test_ask_n0_form_permission_denied(client, run_n0_form_mock):
    """POST /support/ask-n0-form - a user without READ_SUPPORT is rejected [401]"""
    headers = make_headers(get_access(client, roles=[Role.DISPENSING_MANAGER.value]))

    response = client.post(FORM_URL, json={"question": "pergunta"}, headers=headers)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    run_n0_form_mock.assert_not_called()


def test_ask_n0_form_requires_a_question(client, analyst_headers, run_n0_form_mock):
    """POST /support/ask-n0-form - an empty question is rejected [400]"""
    response = client.post(FORM_URL, json={"question": ""}, headers=analyst_headers)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.businessRules"
    run_n0_form_mock.assert_not_called()


def test_ask_n0_form_returns_the_ticket(client, analyst_headers, run_n0_form_mock):
    """POST /support/ask-n0-form - the structured ticket comes back untouched"""
    response = client.post(
        FORM_URL, json={"question": "o relatório não abre"}, headers=analyst_headers
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"] == {"agent": TICKET}
    assert run_n0_form_mock.call_args.kwargs["query"] == "o relatório não abre"
