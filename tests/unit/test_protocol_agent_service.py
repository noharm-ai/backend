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
from repository import exams_repository
from services.protocol_agent_service import (
    LIMIT_TURNS_MESSAGE,
    _is_valid_trigger,
    _normalize_config,
    _run_agent_turn,
    _to_strands_messages,
    _turn_prompt,
    _validate_config,
    _validate_proposal,
)
from services.protocol_agent_tools import _success, build_tools


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


class _ExamTypeRow:
    """Row shape returned by exams_repository.get_exam_types"""

    def __init__(self, type_exam, name="Exame"):
        self.typeExam = type_exam
        self.name = name


class _GlobalExamRow:
    """Row shape returned by exams_repository.get_global_exams"""

    def __init__(self, tp_exam, name="Exame global"):
        self.tp_exam = tp_exam
        self.name = name


def _exam_proposal(variable: dict):
    """A minimal valid proposal whose single variable is the one under test."""
    return {
        "protocolType": 2,
        "config": {
            "variables": [variable],
            "trigger": "{{v1}}",
            "result": {
                "type": "SHOW_MESSAGE",
                "level": "high",
                "message": "Alerta",
                "description": "Descrição",
            },
        },
    }


def _exam_variable(**extra):
    return {"name": "v1", "field": "exam", "operator": ">", "value": 2, **extra}


def _exam_ref_variable(**extra):
    return {"name": "v1", "field": "exam_ref", "operator": ">", "value": 2, **extra}


def _patch_exam_types(*type_exams):
    return mock.patch.object(
        exams_repository,
        "get_exam_types",
        return_value=[_ExamTypeRow(t) for t in type_exams],
    )


def _patch_global_exams(*tp_exams):
    return mock.patch.object(
        exams_repository,
        "get_global_exams",
        return_value=[_GlobalExamRow(t) for t in tp_exams],
    )


def test_unknown_exam_type_is_rejected():
    with _patch_exam_types("potassio", "sodio"):
        errors = _validate_proposal(
            proposal=_exam_proposal(_exam_variable(examType="creatinina_fake")),
            draft={},
        )

    assert len(errors) == 1
    assert "v1" in errors[0]
    assert "creatinina_fake" in errors[0]
    assert "search_exam_types" in errors[0]


def test_known_exam_type_passes():
    with _patch_exam_types("potassio", "sodio"):
        assert (
            _validate_proposal(
                proposal=_exam_proposal(_exam_variable(examType="potassio")), draft={}
            )
            == []
        )


def test_configured_calculated_exam_passes():
    # ckd21 and friends are ordinary segment exam rows when configured, so the
    # catalog already contains them: they must not be rejected
    with _patch_exam_types("ckd21"):
        assert (
            _validate_proposal(
                proposal=_exam_proposal(_exam_variable(examType="ckd21")), draft={}
            )
            == []
        )


@pytest.mark.parametrize("alias", ["cr", "tgo", "tgp", "plqt"])
def test_runtime_alias_exam_types_pass(alias):
    # these keys never appear in the catalog but do exist at runtime
    with _patch_exam_types("potassio"):
        assert (
            _validate_proposal(
                proposal=_exam_proposal(_exam_variable(examType=alias)), draft={}
            )
            == []
        )


def test_exam_type_is_matched_case_insensitively():
    with _patch_exam_types("potassio"):
        assert (
            _validate_proposal(
                proposal=_exam_proposal(_exam_variable(examType="POTASSIO")), draft={}
            )
            == []
        )


def test_unknown_reference_exam_is_rejected():
    with _patch_global_exams("ckd21_nh"):
        errors = _validate_proposal(
            proposal=_exam_proposal(_exam_ref_variable(examRefType="CREAT_FAKE")),
            draft={},
        )

    assert len(errors) == 1
    assert "CREAT_FAKE" in errors[0]
    assert "search_reference_exams" in errors[0]


def test_known_reference_exam_passes():
    with _patch_global_exams("ckd21_nh"):
        assert (
            _validate_proposal(
                proposal=_exam_proposal(_exam_ref_variable(examRefType="ckd21_nh")),
                draft={},
            )
            == []
        )


def test_reference_exam_with_wrong_case_names_the_canonical_spelling():
    # exam_ref is matched verbatim at runtime, so the exact spelling is reported
    # instead of being silently rewritten
    with _patch_global_exams("ckd21_NH"):
        errors = _validate_proposal(
            proposal=_exam_proposal(_exam_ref_variable(examRefType="ckd21_nh")),
            draft={},
        )

    assert len(errors) == 1
    assert "ckd21_NH" in errors[0]


def test_missing_reference_exam_type_is_rejected():
    # _validate_variables has no exam_ref branch, so this gate is the only one
    with _patch_global_exams("ckd21_nh"):
        errors = _validate_proposal(
            proposal=_exam_proposal(_exam_ref_variable()), draft={}
        )

    assert len(errors) == 1
    assert "não informado" in errors[0]


def test_unknown_stats_type_is_rejected():
    errors = _validate_proposal(
        proposal=_exam_proposal(
            {
                "name": "v1",
                "field": "cn_stats",
                "operator": ">",
                "value": 1,
                "statsType": "inventado",
            }
        ),
        draft={},
    )

    assert len(errors) == 1
    assert "inventado" in errors[0]
    assert "list_stats_types" in errors[0]


def test_known_stats_type_passes():
    assert (
        _validate_proposal(
            proposal=_exam_proposal(
                {
                    "name": "v1",
                    "field": "cn_stats",
                    "operator": ">",
                    "value": 1,
                    "statsType": "dialysis",
                }
            ),
            draft={},
        )
        == []
    )


def test_catalog_failure_does_not_block_the_proposal():
    # a database hiccup must not make every proposal invalid
    with mock.patch.object(
        exams_repository, "get_exam_types", side_effect=Exception("db down")
    ):
        assert (
            _validate_proposal(
                proposal=_exam_proposal(_exam_variable(examType="whatever")), draft={}
            )
            == []
        )


def test_catalogs_are_not_loaded_without_exam_variables():
    # the existing suite runs with no database: a proposal that references no
    # catalog must not touch one
    with mock.patch.object(exams_repository, "get_exam_types") as exam_types, (
        mock.patch.object(exams_repository, "get_global_exams")
    ) as global_exams:
        assert _validate_proposal(proposal=_valid_proposal(), draft={}) == []

    exam_types.assert_not_called()
    global_exams.assert_not_called()


def test_normalization_lowercases_exam_type_only():
    config = _normalize_config(
        config={
            "variables": [
                _exam_variable(examType="  POTASSIO "),
                _exam_ref_variable(examRefType="ckd21_NH"),
            ],
            "trigger": "{{v1}}",
        }
    )

    assert config["variables"][0]["examType"] == "potassio"
    # matched verbatim at runtime, so it must survive untouched
    assert config["variables"][1]["examRefType"] == "ckd21_NH"


def test_success_reports_truncation_for_long_lists():
    payload = _success(list(range(60)), max_results=50)["content"][0]["json"]["result"]

    assert payload["total"] == 60
    assert payload["returned"] == 50
    assert payload["truncated"] is True
    assert payload["items"] == list(range(50))


def test_success_does_not_report_truncation_for_short_lists():
    payload = _success([1, 2, 3], max_results=50)["content"][0]["json"]["result"]

    assert payload["total"] == 3
    assert payload["truncated"] is False


def test_success_passes_dict_results_through_unwrapped():
    # validate_protocol and test_protocol return dicts: wrapping them in items
    # would break the self-correction loop the agent depends on
    result = {"valid": False, "errors": ["boom"]}

    assert _success(result)["content"][0]["json"]["result"] == result


def test_validate_protocol_tool_reports_an_invented_exam():
    """The tool is the only place the agent sees its own mistake.

    proposalErrors returned by chat() go to the frontend, which replays only
    role and content, so a rejected proposal never reaches the model. The
    validate_protocol tool result does, inside the same turn.
    """
    tools = {
        t.tool_spec["name"]: t
        for t in build_tools(
            schema="demo",
            validate_config=_validate_config,
            normalize_config=_normalize_config,
        )
    }

    with mock.patch("services.protocol_agent_tools.dbSession.setSchema"), (
        _patch_global_exams("ckd21_nh")
    ):
        output = tools["validate_protocol"]._tool_func(
            config=_exam_proposal(_exam_ref_variable(examRefType="CREAT_FAKE"))[
                "config"
            ],
            protocol_type=2,
        )

    assert output["status"] == "success"
    result = output["content"][0]["json"]["result"]
    assert result["valid"] is False
    assert any("CREAT_FAKE" in e for e in result["errors"])
    assert any("search_reference_exams" in e for e in result["errors"])


def test_sentinel_exam_value_is_rejected():
    # the model reaches for an impossible value to mean "no such exam"
    with _patch_global_exams("creatinina_NH"):
        errors = _validate_proposal(
            proposal=_exam_proposal(
                _exam_ref_variable(
                    examRefType="creatinina_NH", operator="=", value=-999
                )
            ),
            draft={},
        )

    assert len(errors) == 1
    assert "-999" in errors[0]
    assert "not" in errors[0]


def test_absence_pattern_passes():
    # the supported way to express absence: positive variable, negated trigger
    with _patch_global_exams("creatinina_NH"):
        proposal = _exam_proposal(
            _exam_ref_variable(examRefType="creatinina_NH", operator=">", value=0)
        )
        proposal["config"]["trigger"] = "not {{v1}}"

        assert _validate_proposal(proposal=proposal, draft={}) == []


def test_negated_trigger_is_accepted_by_the_trigger_validator():
    assert _is_valid_trigger(trigger="not {{v1}}", variable_names=["v1"])
    assert _is_valid_trigger(
        trigger="{{v1}} and not {{v2}}", variable_names=["v1", "v2"]
    )


def test_plausible_negative_threshold_is_not_treated_as_a_sentinel():
    # some exams are legitimately negative (base excess, delta values)
    with _patch_exam_types("be"):
        assert (
            _validate_proposal(
                proposal=_exam_proposal(
                    _exam_variable(examType="be", operator="<", value=-5)
                ),
                draft={},
            )
            == []
        )
