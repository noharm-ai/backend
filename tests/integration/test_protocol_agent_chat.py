"""Integration tests for POST /protocol/ai/agent-chat (protocol_agent_service.chat).

The protocol creation co-pilot answers one stateless chat turn: the frontend
holds the transcript and the current form draft, posts them with the new
message, and gets back the agent's reply plus — when the agent has enough
information — a complete protocol proposal the user can accept into the form.

The endpoint and ``chat`` itself had no test. The pieces around them do
(``tests/unit/test_protocol_agent_service.py`` covers the agent turn, the
proposal validator and the config normalizer), but not the gate that joins
them, which is where the safety property of this feature lives: **a proposal
that does not validate is never handed to the user**. The agent is told to call
validate_protocol before proposing, yet a model can propose anyway; ``chat`` is
what stops an invalid protocol from reaching the form, and it has to normalize
the config first so a proposal is not rejected over a shape the system already
knows how to fix.

The Bedrock turn is mocked throughout — ``_run_agent_turn`` is covered on its
own and nothing here should reach AWS. Everything else is real: the route, the
JWT, the permission gate, the request validation and the proposal validator
(which queries the database).
"""

from unittest import mock

import pytest

from exception.validation_error import ValidationError
from models.response.agents.protocol_agent_response import (
    ProtocolAgentProposal,
    ProtocolAgentProposalConfig,
    ProtocolAgentTurnOutput,
)
from security.role import Role
from services.protocol_agent_service import MAX_MESSAGE_LENGTH
from tests.conftest import get_access, make_headers
from utils import status

URL = "/protocol/ai/agent-chat"


@pytest.fixture
def protocol_author_headers(client):
    """Headers with CURATOR role — one of the roles holding WRITE_PROTOCOLS"""
    return make_headers(get_access(client, roles=[Role.CURATOR.value]))


def _request(**overrides):
    """A chat turn as the protocol form posts it."""
    body = {
        "messages": [
            {"role": "user", "content": "quero um protocolo para idosos"},
            {"role": "assistant", "content": "qual substância deve ser monitorada?"},
        ],
        "draft": {"name": "Idoso", "protocolType": 2, "config": {}},
        "message": "alerta para pacientes acima de 60 anos",
    }
    body.update(overrides)
    return body


def _valid_config():
    """A proposal config that passes the protocol validator."""
    return {
        "variables": [
            {"name": "v1", "field": "age", "operator": ">", "value": 60},
            {
                "name": "v2",
                "field": "substance",
                "operator": "IN",
                "value": ["111111"],
            },
        ],
        "trigger": "{{v1}} and {{v2}}",
        "result": {
            "type": "SHOW_MESSAGE",
            "level": "high",
            "message": "Paciente idoso em uso de substância monitorada",
            "description": "Avaliar necessidade de ajuste",
        },
    }


def _turn(message="<p>Pronto</p>", config=None, protocol_type=2, name="Idoso"):
    """What the agent returns for one turn; ``config=None`` means no proposal."""
    proposal = None
    if config is not None:
        proposal = ProtocolAgentProposal(
            name=name,
            protocolType=protocol_type,
            config=ProtocolAgentProposalConfig(**config),
        )

    return ProtocolAgentTurnOutput(message=message, proposal=proposal)


def _post(client, headers, turn=None, body=None, error=None):
    """Post a chat turn with the Bedrock agent answering ``turn`` (or raising)."""
    patched = mock.patch(
        "services.protocol_agent_service._run_agent_turn",
        side_effect=error,
        **({} if error else {"return_value": turn if turn else _turn()}),
    )

    with patched as mock_turn:
        response = client.post(
            URL, json=body if body is not None else _request(), headers=headers
        )

    return response, mock_turn


def _data(response):
    """The payload of a successful answer."""
    return response.get_json()["data"]


# --------------------------------------------------------------------------
# permission gate
# --------------------------------------------------------------------------


def test_a_role_without_write_protocols_cannot_use_the_copilot(
    client, analyst_headers
):
    """Teste POST /protocol/ai/agent-chat - perfil sem WRITE_PROTOCOLS recebe 401"""
    response, mock_turn = _post(client, analyst_headers)

    assert response.status_code == 401
    assert response.get_json()["code"] == "error.authorizationError"
    mock_turn.assert_not_called()


def test_the_copilot_is_unavailable_without_a_token(client):
    """Teste POST /protocol/ai/agent-chat - requisição sem JWT recebe 401"""
    response = client.post(URL, json=_request())

    assert response.status_code == 401


def test_a_protocol_author_reaches_the_copilot(client, protocol_author_headers):
    """Teste POST /protocol/ai/agent-chat - perfil com WRITE_PROTOCOLS é aceito"""
    response, _ = _post(client, protocol_author_headers)

    assert response.status_code == 200
    assert response.get_json()["status"] == "success"


# --------------------------------------------------------------------------
# what reaches the agent
# --------------------------------------------------------------------------


def test_the_transcript_draft_and_message_reach_the_agent(
    client, protocol_author_headers
):
    """Teste POST /protocol/ai/agent-chat - transcrição, rascunho e mensagem são repassados"""
    _, mock_turn = _post(client, protocol_author_headers)

    request_data = mock_turn.call_args.kwargs["request_data"]

    assert [(m.role, m.content) for m in request_data.messages] == [
        ("user", "quero um protocolo para idosos"),
        ("assistant", "qual substância deve ser monitorada?"),
    ]
    assert request_data.draft.name == "Idoso"
    assert request_data.draft.protocolType == 2
    assert request_data.message == "alerta para pacientes acima de 60 anos"


def test_the_caller_schema_reaches_the_agent(client, protocol_author_headers):
    """Teste POST /protocol/ai/agent-chat - as ferramentas do agente recebem o schema do usuário"""
    _, mock_turn = _post(client, protocol_author_headers)

    assert mock_turn.call_args.kwargs["user_context"].schema == "demo"


def test_a_first_turn_has_no_transcript(client, protocol_author_headers):
    """Teste POST /protocol/ai/agent-chat - a primeira mensagem da conversa é aceita"""
    response, mock_turn = _post(
        client,
        protocol_author_headers,
        body={"message": "como crio um protocolo?"},
    )

    assert response.status_code == 200
    assert mock_turn.call_args.kwargs["request_data"].messages == []


# --------------------------------------------------------------------------
# the answer
# --------------------------------------------------------------------------


def test_a_turn_without_a_proposal_is_only_a_message(client, protocol_author_headers):
    """Teste POST /protocol/ai/agent-chat - turno de pergunta responde sem proposta"""
    response, _ = _post(
        client,
        protocol_author_headers,
        turn=_turn(message="<p>Qual substância?</p>"),
    )

    assert _data(response) == {
        "message": "<p>Qual substância?</p>",
        "proposal": None,
        "proposalErrors": [],
    }


def test_a_valid_proposal_is_handed_to_the_form(client, protocol_author_headers):
    """Teste POST /protocol/ai/agent-chat - proposta válida chega completa ao formulário"""
    response, _ = _post(
        client, protocol_author_headers, turn=_turn(config=_valid_config())
    )

    data = _data(response)

    assert data["proposalErrors"] == []
    assert data["proposal"]["name"] == "Idoso"
    assert data["proposal"]["protocolType"] == 2
    assert data["proposal"]["config"]["trigger"] == "{{v1}} and {{v2}}"
    assert [v["name"] for v in data["proposal"]["config"]["variables"]] == ["v1", "v2"]


def test_the_message_is_trimmed(client, protocol_author_headers):
    """Teste POST /protocol/ai/agent-chat - espaços em volta da mensagem são removidos"""
    response, _ = _post(
        client, protocol_author_headers, turn=_turn(message="  <p>Pronto</p>\n ")
    )

    assert _data(response)["message"] == "<p>Pronto</p>"


def test_a_long_message_is_truncated(client, protocol_author_headers):
    """Teste POST /protocol/ai/agent-chat - mensagem longa é cortada no limite"""
    response, _ = _post(
        client,
        protocol_author_headers,
        turn=_turn(message="a" * (MAX_MESSAGE_LENGTH + 500)),
    )

    assert len(_data(response)["message"]) == MAX_MESSAGE_LENGTH


def test_an_empty_message_stays_empty(client, protocol_author_headers):
    """Teste POST /protocol/ai/agent-chat - turno sem texto responde string vazia"""
    response, _ = _post(client, protocol_author_headers, turn=_turn(message="   "))

    assert _data(response)["message"] == ""


# --------------------------------------------------------------------------
# the validation gate — an invalid proposal must never reach the form
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "broken,expected",
    [
        pytest.param(
            {"trigger": "{{v1}} and {{fantasma}}"},
            "Gatilho possui formato inválido",
            id="trigger-names-an-undeclared-variable",
        ),
        pytest.param(
            {"trigger": ""},
            "Gatilho não informado",
            id="no-trigger",
        ),
        pytest.param(
            {
                "result": {
                    "type": "SHOW_MESSAGE",
                    "level": "altíssimo",
                    "message": "Alerta",
                    "description": "",
                }
            },
            "Nível de alerta inválido",
            id="unknown-alert-level",
        ),
        pytest.param(
            {
                "result": {
                    "type": "SHOW_MESSAGE",
                    "level": "high",
                    "message": "   ",
                    "description": "",
                }
            },
            "Mensagem de alerta não informada",
            id="no-alert-message",
        ),
    ],
)
def test_an_invalid_proposal_is_withheld_and_the_reason_reported(
    client, protocol_author_headers, broken, expected
):
    """Teste POST /protocol/ai/agent-chat - proposta inválida é retida e o erro informado.

    O agente é instruído a validar antes de propor, mas nada garante que o
    modelo obedeça: é esta porta que impede um protocolo inválido de chegar
    ao formulário.
    """
    response, _ = _post(
        client,
        protocol_author_headers,
        turn=_turn(config={**_valid_config(), **broken}),
    )

    data = _data(response)

    assert data["proposal"] is None
    assert expected in data["proposalErrors"]


def test_the_message_survives_a_withheld_proposal(client, protocol_author_headers):
    """Teste POST /protocol/ai/agent-chat - a resposta do agente é exibida mesmo sem a proposta"""
    response, _ = _post(
        client,
        protocol_author_headers,
        turn=_turn(
            message="<p>Segue a proposta</p>",
            config={**_valid_config(), "trigger": "{{fantasma}}"},
        ),
    )

    data = _data(response)

    assert data["message"] == "<p>Segue a proposta</p>"
    assert data["proposal"] is None
    assert data["proposalErrors"] != []


def test_a_proposal_without_a_protocol_type_falls_back_to_the_draft(
    client, protocol_author_headers
):
    """Teste POST /protocol/ai/agent-chat - o tipo do rascunho vale quando a proposta omite"""
    response, _ = _post(
        client,
        protocol_author_headers,
        turn=_turn(config=_valid_config(), protocol_type=None),
    )

    data = _data(response)

    assert data["proposalErrors"] == []
    assert data["proposal"] is not None


def test_a_proposal_without_a_protocol_type_anywhere_is_withheld(
    client, protocol_author_headers
):
    """Teste POST /protocol/ai/agent-chat - sem tipo na proposta nem no rascunho a proposta é retida"""
    response, _ = _post(
        client,
        protocol_author_headers,
        turn=_turn(config=_valid_config(), protocol_type=None),
        body=_request(draft={"name": "Sem tipo"}),
    )

    data = _data(response)

    assert data["proposal"] is None
    assert data["proposalErrors"] == ["Tipo de protocolo inválido ou não informado"]


def test_a_combination_wrapped_in_operator_and_value_is_flattened(
    client, protocol_author_headers
):
    """Teste POST /protocol/ai/agent-chat - critérios aninhados de combination são achatados antes de validar.

    O modelo costuma responder a variável combination como
    {"operator": "PRESENT", "value": {...}}; nenhuma das duas chaves existe
    nesse campo. A proposta é normalizada antes da validação, para não ser
    recusada por um formato que o sistema sabe corrigir.
    """
    config = {
        "variables": [
            {
                "name": "dipirona_oral_dose_alta",
                "field": "combination",
                "operator": "PRESENT",
                "value": {
                    "substance": ["22165008"],
                    "route": ["Oral"],
                    "dose": 200,
                    "doseOperator": ">",
                },
            }
        ],
        "trigger": "{{dipirona_oral_dose_alta}}",
        "result": {
            "type": "SHOW_MESSAGE",
            "level": "low",
            "message": "Dipirona oral com dose acima de 200 mg",
            "description": "Verificar se a dose está adequada",
        },
    }

    response, _ = _post(
        client,
        protocol_author_headers,
        turn=_turn(config=config, protocol_type=4),
    )

    data = _data(response)
    variable = data["proposal"]["config"]["variables"][0]

    assert data["proposalErrors"] == []
    assert variable["substance"] == ["22165008"]
    assert variable["dose"] == 200
    assert "operator" not in variable
    assert "value" not in variable


# --------------------------------------------------------------------------
# request validation
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({}, id="no-message"),
        pytest.param({"message": ""}, id="blank-message"),
        pytest.param({"message": "a" * 2001}, id="message-over-the-limit"),
        pytest.param(
            {"message": "oi", "messages": [{"role": "system", "content": "x"}]},
            id="unknown-transcript-role",
        ),
        pytest.param(
            {"message": "oi", "messages": [{"role": "user", "content": ""}]},
            id="blank-transcript-turn",
        ),
        pytest.param(
            {
                "message": "oi",
                "messages": [{"role": "user", "content": "x"}] * 41,
            },
            id="transcript-over-the-limit",
        ),
    ],
)
def test_an_invalid_request_is_rejected_before_the_agent_runs(
    client, protocol_author_headers, body
):
    """Teste POST /protocol/ai/agent-chat - requisição inválida recebe 400 sem chamar o agente"""
    response, mock_turn = _post(client, protocol_author_headers, body=body)

    assert response.status_code == 400
    assert response.get_json()["status"] == "error"
    mock_turn.assert_not_called()


def test_a_transcript_at_the_limit_is_accepted(client, protocol_author_headers):
    """Teste POST /protocol/ai/agent-chat - uma transcrição no limite ainda é aceita"""
    response, _ = _post(
        client,
        protocol_author_headers,
        body=_request(messages=[{"role": "user", "content": "x"}] * 40),
    )

    assert response.status_code == 200


# --------------------------------------------------------------------------
# the agent is unavailable
# --------------------------------------------------------------------------


def test_an_unavailable_agent_is_reported_as_503(client, protocol_author_headers):
    """Teste POST /protocol/ai/agent-chat - indisponibilidade do Bedrock vira 503"""
    response, _ = _post(
        client,
        protocol_author_headers,
        error=ValidationError(
            "Serviço de IA indisponível",
            "errors.serviceUnavailable",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        ),
    )

    assert response.status_code == 503
    assert response.get_json()["code"] == "errors.serviceUnavailable"
