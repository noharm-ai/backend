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
    _is_valid_trigger,
    _normalize_config,
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


def _nested_combination_config():
    """The shape the model actually produces for a combo: criteria under value."""
    return {
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


def test_nested_combination_criteria_are_flattened():
    config = _normalize_config(config=_nested_combination_config())

    assert config["variables"] == [
        {
            "name": "dipirona_oral_dose_alta",
            "field": "combination",
            "substance": ["22165008"],
            "route": ["Oral"],
            "dose": 200,
            "doseOperator": ">",
        }
    ]


def test_flat_combination_criteria_win_over_nested_ones():
    config = _nested_combination_config()
    config["variables"][0]["dose"] = 500

    normalized = _normalize_config(config=config)

    assert normalized["variables"][0]["dose"] == 500


def test_normalization_keeps_other_variables_untouched():
    config = _valid_proposal()["config"]

    assert _normalize_config(config=config) == config


def test_combination_wrapped_in_combination_key_is_flattened():
    config = _nested_combination_config()
    variable = config["variables"][0]
    variable["combination"] = variable.pop("value")

    normalized = _normalize_config(config=config)

    assert normalized["variables"][0]["substance"] == ["22165008"]
    assert "combination" not in normalized["variables"][0]


def test_item_protocol_with_nested_combination_passes_after_normalization():
    proposal = {
        "protocolType": 4,
        "config": _normalize_config(config=_nested_combination_config()),
    }

    assert _validate_proposal(proposal=proposal, draft={}) == []


def test_combination_without_any_criteria_is_rejected():
    proposal = {
        "protocolType": 4,
        "config": {
            **_nested_combination_config(),
            "variables": [{"name": "combo", "field": "combination"}],
        },
    }
    proposal["config"]["trigger"] = "{{combo}}"

    errors = _validate_proposal(proposal=proposal, draft={})

    assert any("sem nenhum critério" in error for error in errors)


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


def test_valid_trigger_passes():
    assert _is_valid_trigger(
        trigger="{{v1}} and not ({{v2}} or {{v1}})", variable_names=["v1", "v2"]
    )


def test_unknown_variable_is_rejected():
    assert not _is_valid_trigger(
        trigger="{{v1}} and {{ghost}}", variable_names=["v1"]
    )


def test_unbalanced_parentheses_are_rejected():
    assert not _is_valid_trigger(
        trigger="({{v1}} and {{v2}}", variable_names=["v1", "v2"]
    )


def test_disallowed_tokens_are_rejected():
    assert not _is_valid_trigger(
        trigger="__import__('os').system('id')", variable_names=["v1"]
    )
