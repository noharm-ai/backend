"""Test: protocol agent service (proposal validation gate + agent turn handling)"""

from unittest import mock

import pytest
from botocore.exceptions import ReadTimeoutError

from exception.validation_error import ValidationError
from models.requests.protocol_agent_request import (
    ProtocolAgentChatMessage,
    ProtocolAgentChatRequest,
    ProtocolAgentDraft,
)
from models.response.agents.protocol_agent_response import ProtocolAgentTurnOutput
from services.protocol_agent_service import (
    LIMIT_TURNS_MESSAGE,
    _run_agent_turn,
    _to_strands_messages,
    _turn_prompt,
    _validate_proposal,
)


def _valid_proposal():
    return {
        "protocolType": 2,
        "config": {
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
        },
    }


def test_valid_proposal_passes():
    assert _validate_proposal(proposal=_valid_proposal(), draft={}) == []


def test_protocol_type_from_draft_is_used():
    proposal = _valid_proposal()
    proposal.pop("protocolType")

    assert _validate_proposal(proposal=proposal, draft={"protocolType": 2}) == []


def test_missing_protocol_type_is_rejected():
    proposal = _valid_proposal()
    proposal.pop("protocolType")

    errors = _validate_proposal(proposal=proposal, draft={})

    assert errors == ["Tipo de protocolo inválido ou não informado"]


def test_unknown_variable_in_trigger_is_rejected():
    proposal = _valid_proposal()
    proposal["config"]["trigger"] = "{{v1}} and {{ghost}}"

    errors = _validate_proposal(proposal=proposal, draft={})

    assert "Gatilho possui formato inválido" in errors


def test_in_operator_with_scalar_value_is_rejected():
    proposal = _valid_proposal()
    proposal["config"]["variables"][1]["value"] = "111111"

    errors = _validate_proposal(proposal=proposal, draft={})

    assert any("lista" in error for error in errors)


def test_missing_result_message_is_rejected():
    proposal = _valid_proposal()
    proposal["config"]["result"]["message"] = ""

    errors = _validate_proposal(proposal=proposal, draft={})

    assert "Mensagem de alerta não informada" in errors


def test_invalid_result_level_is_rejected():
    proposal = _valid_proposal()
    proposal["config"]["result"]["level"] = "critical"

    errors = _validate_proposal(proposal=proposal, draft={})

    assert "Nível de alerta inválido" in errors


def test_item_protocol_without_combination_is_rejected():
    proposal = _valid_proposal()
    proposal["protocolType"] = 4

    errors = _validate_proposal(proposal=proposal, draft={})

    assert any("COMBO" in error for error in errors)


def test_non_dict_proposal_is_rejected():
    assert _validate_proposal(proposal="not a dict", draft={}) == [
        "Proposta inválida"
    ]
    assert _validate_proposal(proposal={"config": None}, draft={}) == [
        "Proposta sem configuração"
    ]


def _chat_request():
    return ProtocolAgentChatRequest(
        messages=[
            ProtocolAgentChatMessage(role="user", content="quero um protocolo"),
            ProtocolAgentChatMessage(role="assistant", content="qual o objetivo?"),
        ],
        draft=ProtocolAgentDraft(name="Idoso", protocolType=2, config={}),
        message="alerta para pacientes acima de 60 anos",
    )


def _user():
    user = mock.Mock()
    user.schema = "demo"
    return user


def test_to_strands_messages_maps_transcript():
    messages = _to_strands_messages(request_data=_chat_request())

    assert messages == [
        {"role": "user", "content": [{"text": "quero um protocolo"}]},
        {"role": "assistant", "content": [{"text": "qual o objetivo?"}]},
    ]


def test_turn_prompt_contains_draft_and_message():
    prompt = _turn_prompt(request_data=_chat_request())

    assert "<rascunho_atual>" in prompt
    assert '"Idoso"' in prompt
    assert "<mensagem_usuario>alerta para pacientes acima de 60 anos" in prompt


def _agent_result(stop_reason="end_turn", structured_output=None):
    result = mock.Mock()
    result.stop_reason = stop_reason
    result.structured_output = structured_output
    return result


@mock.patch("services.protocol_agent_service.build_tools", return_value=[])
@mock.patch("services.protocol_agent_service.BedrockModel")
@mock.patch("services.protocol_agent_service.Agent")
def test_run_agent_turn_returns_structured_output(
    mock_agent_cls, _mock_model, _mock_tools
):
    output = ProtocolAgentTurnOutput(message="olá", proposal=None)
    mock_agent_cls.return_value.return_value = _agent_result(
        structured_output=output
    )

    turn = _run_agent_turn(request_data=_chat_request(), user_context=_user())

    assert turn is output


@mock.patch("services.protocol_agent_service.build_tools", return_value=[])
@mock.patch("services.protocol_agent_service.BedrockModel")
@mock.patch("services.protocol_agent_service.Agent")
def test_run_agent_turn_limit_turns_returns_fallback_message(
    mock_agent_cls, _mock_model, _mock_tools
):
    mock_agent_cls.return_value.return_value = _agent_result(
        stop_reason="limit_turns", structured_output=None
    )

    turn = _run_agent_turn(request_data=_chat_request(), user_context=_user())

    assert turn.message == LIMIT_TURNS_MESSAGE
    assert turn.proposal is None


@mock.patch("services.protocol_agent_service.build_tools", return_value=[])
@mock.patch("services.protocol_agent_service.BedrockModel")
@mock.patch("services.protocol_agent_service.Agent")
def test_run_agent_turn_read_timeout_raises_503(
    mock_agent_cls, _mock_model, _mock_tools
):
    mock_agent_cls.return_value.side_effect = ReadTimeoutError(
        endpoint_url="https://bedrock"
    )

    with pytest.raises(ValidationError) as error:
        _run_agent_turn(request_data=_chat_request(), user_context=_user())

    assert error.value.code == "errors.serviceUnavailable"


@mock.patch("services.protocol_agent_service.build_tools", return_value=[])
@mock.patch("services.protocol_agent_service.BedrockModel")
@mock.patch("services.protocol_agent_service.Agent")
def test_run_agent_turn_generic_failure_raises_503(
    mock_agent_cls, _mock_model, _mock_tools
):
    mock_agent_cls.return_value.side_effect = Exception("boom")

    with pytest.raises(ValidationError) as error:
        _run_agent_turn(request_data=_chat_request(), user_context=_user())

    assert error.value.code == "errors.serviceUnavailable"


@mock.patch("services.protocol_agent_service.build_tools", return_value=[])
@mock.patch("services.protocol_agent_service.BedrockModel")
@mock.patch("services.protocol_agent_service.Agent")
def test_run_agent_turn_missing_structured_output_raises_503(
    mock_agent_cls, _mock_model, _mock_tools
):
    mock_agent_cls.return_value.return_value = _agent_result(
        stop_reason="end_turn", structured_output=None
    )

    with pytest.raises(ValidationError) as error:
        _run_agent_turn(request_data=_chat_request(), user_context=_user())

    assert error.value.code == "errors.serviceUnavailable"


@mock.patch("services.protocol_agent_service.build_tools", return_value=[])
@mock.patch("services.protocol_agent_service.BedrockModel")
@mock.patch("services.protocol_agent_service.Agent")
def test_run_agent_turn_guardrail_raises_503(
    mock_agent_cls, _mock_model, _mock_tools
):
    mock_agent_cls.return_value.return_value = _agent_result(
        stop_reason="guardrail_intervened"
    )

    with pytest.raises(ValidationError) as error:
        _run_agent_turn(request_data=_chat_request(), user_context=_user())

    assert error.value.code == "errors.serviceUnavailable"
