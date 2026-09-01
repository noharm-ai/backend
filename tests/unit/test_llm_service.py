"""Unit tests for services.llm_service.

``prompt`` is what backs ``POST /summary/prompt``: the discharge-summary screen
sends a chat transcript and gets the model's answer back. Which model answers is
not a request parameter — it is read from the ``summary-config`` global memory
record, so a single row switches every client at once. That indirection is the
whole risk of the feature, and it is what these tests pin down:

* the provider name in ``summary-config`` selects the branch, and anything the
  service does not know about (a missing record, a typo, a provider that was
  removed) is refused with a 400 instead of falling through to ``None``;
* ``openai_azure`` and ``maritaca`` are accepted by the config check but are not
  implemented, so they must fail loudly rather than look like a working setup;
* the three Bedrock providers each speak a different dialect — region, model id,
  request body and the path to the answer inside the response all differ, and
  ``llama`` additionally has to render the chat transcript into a single
  prompt string with Llama 3 header tokens;
* ``gpt_oss`` returns its chain of thought in ``<reasoning>`` tags, which must
  be stripped before the text reaches a clinical user.

Bedrock is mocked at ``utils.aws.get_client`` and the config row is mocked at
the session, so no AWS call and no database is needed.
"""

import json
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from exception.authorization_error import AuthorizationError
from exception.validation_error import ValidationError
from mobile import app
from models.appendix import GlobalMemory
from security.role import Role
from services import llm_service

# Undecorated business logic (skips the permission gate).
_prompt = llm_service.prompt.__wrapped__

MESSAGES = [
    {"role": "user", "content": "Resuma a internação"},
    {"role": "assistant", "content": "Paciente estável"},
]


def _config(provider):
    """Build the ``summary-config`` global memory row naming ``provider``."""
    memory = GlobalMemory()
    memory.kind = "summary-config"
    memory.value = {"provider": provider, "prompt-config": "summary-prompt"}
    return memory


@contextmanager
def summary_config(provider):
    """Answer the service's ``summary-config`` lookup with ``provider``.

    ``provider=None`` stands for "no config row at all".
    """
    value = _config(provider) if provider is not None else None
    mock_db = MagicMock()
    mock_db.session.query.return_value.filter.return_value.first.return_value = value

    with patch.object(llm_service, "db", mock_db):
        yield


@contextmanager
def bedrock(payload):
    """Mock the Bedrock client so ``invoke_model`` answers with ``payload``.

    Yields the client mock, whose ``invoke_model`` call args carry the request
    the service built, and the ``get_client`` mock, which carries the region.
    """
    client = MagicMock()
    body = MagicMock()
    body.read.return_value = json.dumps(payload).encode("utf-8")
    client.invoke_model.return_value = {"body": body}

    with patch.object(
        llm_service.aws, "get_client", return_value=client
    ) as get_client:
        yield client, get_client


def _request_body(client):
    """The JSON body the service sent to ``invoke_model``, decoded."""
    return json.loads(client.invoke_model.call_args.kwargs["body"])


@contextmanager
def acting_as(roles):
    """Run the block inside a request context authenticated as ``roles``.

    Patches the permission decorator's JWT identity lookup and ``User`` model
    so the decorated service resolves a fabricated user carrying ``roles``.
    """
    fake_user = MagicMock()
    fake_user.id = 7
    fake_user.config = {"roles": roles}
    with app.test_request_context():
        with patch(
            "decorators.has_permission_decorator.get_jwt_identity", return_value=1
        ), patch("decorators.has_permission_decorator.User") as mock_user_cls:
            mock_user_cls.find.return_value = fake_user
            yield


# --------------------------------------------------------------------------
# nothing to ask
# --------------------------------------------------------------------------


@pytest.mark.parametrize("messages", [None, []])
def test_an_empty_transcript_short_circuits(messages):
    """No messages means no model call at all, not an empty-transcript request."""
    with patch.object(llm_service.aws, "get_client") as get_client:
        assert _prompt(messages) == ""

    get_client.assert_not_called()


# --------------------------------------------------------------------------
# provider selection
# --------------------------------------------------------------------------


def test_a_missing_summary_config_is_refused():
    """Without the config row there is no provider to route to."""
    with summary_config(None):
        with pytest.raises(ValidationError) as exc:
            _prompt(MESSAGES)

    assert exc.value.code == "errors.invalidParams"
    assert exc.value.httpStatus == 400


@pytest.mark.parametrize("provider", ["", "openai", "bedrock", "OPENAI_AZURE"])
def test_an_unknown_provider_is_refused(provider):
    """Only the five known provider names are accepted, exactly as spelled."""
    with summary_config(provider):
        with pytest.raises(ValidationError) as exc:
            _prompt(MESSAGES)

    assert exc.value.code == "errors.invalidParams"
    assert exc.value.httpStatus == 400


@pytest.mark.parametrize("provider", ["openai_azure", "maritaca"])
def test_a_configured_but_unimplemented_provider_fails_loudly(provider):
    """These two pass the config check but have no implementation behind them.

    They must raise rather than return ``None``, so a half-finished setup is
    visible instead of looking like a model that answered with nothing.
    """
    with summary_config(provider):
        with pytest.raises(ValidationError) as exc:
            _prompt(MESSAGES)

    assert exc.value.code == "errors.invalidModule"
    assert exc.value.httpStatus == 400


# --------------------------------------------------------------------------
# claude
# --------------------------------------------------------------------------


def test_claude_sends_the_transcript_and_returns_the_first_content_block():
    """Claude takes the messages as-is and answers in content[0].text."""
    payload = {"content": [{"type": "text", "text": "Resumo clínico"}]}

    with summary_config("claude"):
        with bedrock(payload) as (client, get_client):
            result = _prompt(MESSAGES)

    assert result == {"answer": "Resumo clínico"}
    get_client.assert_called_once_with("bedrock-runtime", region_name="us-east-1")

    call = client.invoke_model.call_args.kwargs
    assert call["modelId"] == "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    assert call["accept"] == "application/json"
    assert call["contentType"] == "application/json"

    assert _request_body(client) == {
        "max_tokens": 1024,
        "messages": MESSAGES,
        "anthropic_version": "bedrock-2023-05-31",
    }


# --------------------------------------------------------------------------
# gpt_oss
# --------------------------------------------------------------------------


def test_gpt_oss_answers_from_the_first_choice():
    """gpt_oss speaks the OpenAI shape: choices[0].message.content."""
    payload = {"choices": [{"message": {"content": "Resumo gpt"}}]}

    with summary_config("gpt_oss"):
        with bedrock(payload) as (client, get_client):
            result = _prompt(MESSAGES)

    assert result == {"answer": "Resumo gpt"}
    get_client.assert_called_once_with("bedrock-runtime", region_name="us-east-1")

    call = client.invoke_model.call_args.kwargs
    assert call["modelId"] == "openai.gpt-oss-120b-1:0"

    # no anthropic_version here — the body is the plain OpenAI shape
    assert _request_body(client) == {"max_tokens": 1024, "messages": MESSAGES}


def test_gpt_oss_strips_the_reasoning_block_from_the_answer():
    """The chain of thought must never reach a clinical user.

    The block spans lines, so the strip has to be DOTALL — a line-by-line
    match would leave the reasoning text behind.
    """
    answer = (
        "<reasoning>o paciente\nusa dois anti-hipertensivos</reasoning>"
        "Paciente em uso de anti-hipertensivos."
    )

    with summary_config("gpt_oss"):
        with bedrock({"choices": [{"message": {"content": answer}}]}):
            result = _prompt(MESSAGES)

    assert result == {"answer": "Paciente em uso de anti-hipertensivos."}


def test_gpt_oss_strips_every_reasoning_block():
    """More than one block can come back, and each has to go."""
    answer = "<reasoning>um</reasoning>A<reasoning>dois</reasoning>B"

    with summary_config("gpt_oss"):
        with bedrock({"choices": [{"message": {"content": answer}}]}):
            result = _prompt(MESSAGES)

    assert result == {"answer": "AB"}


def test_gpt_oss_leaves_an_answer_without_reasoning_untouched():
    """No tags means nothing to strip — the text is returned verbatim."""
    with summary_config("gpt_oss"):
        with bedrock({"choices": [{"message": {"content": "Sem raciocínio"}}]}):
            result = _prompt(MESSAGES)

    assert result == {"answer": "Sem raciocínio"}


# --------------------------------------------------------------------------
# llama
# --------------------------------------------------------------------------


def test_llama_renders_the_transcript_into_a_single_prompt():
    """Llama takes text, not messages, so the transcript is templated.

    Every message becomes a header/content/eot triple and the string ends with
    an open assistant header, which is what makes the model answer next.
    """
    with summary_config("llama"):
        with bedrock({"generation": "Resumo llama"}) as (client, get_client):
            result = _prompt(MESSAGES)

    assert result == {"answer": "Resumo llama"}
    # llama lives in a different region from claude and gpt_oss
    get_client.assert_called_once_with("bedrock-runtime", region_name="us-west-2")

    call = client.invoke_model.call_args.kwargs
    assert call["modelId"] == "meta.llama3-1-405b-instruct-v1:0"

    body = _request_body(client)
    assert body["prompt"] == (
        "<|begin_of_text|>"
        "<|start_header_id|>user<|end_header_id|>\n"
        "Resuma a internação<|eot_id|>\n"
        "<|start_header_id|>assistant<|end_header_id|>\n"
        "Paciente estável<|eot_id|>\n"
        "<|start_header_id|>assistant<|end_header_id|>"
    )
    assert body["max_gen_len"] == 1024
    assert body["temperature"] == 0.5
    assert body["top_p"] == 0.9
    assert "messages" not in body


# --------------------------------------------------------------------------
# permission gate
# --------------------------------------------------------------------------


def test_prompt_requires_the_discharge_summary_permission():
    """PRESCRIPTION_ANALYST has no READ_DISCHARGE_SUMMARY, so it cannot prompt."""
    with acting_as([Role.PRESCRIPTION_ANALYST.value]):
        with pytest.raises(AuthorizationError):
            llm_service.prompt(MESSAGES)


def test_navigator_passes_the_gate():
    """NAVIGATOR carries READ_DISCHARGE_SUMMARY, so the gate lets it in.

    Reaching the invalid-config error proves the body ran.
    """
    with acting_as([Role.NAVIGATOR.value]):
        with summary_config(None):
            with pytest.raises(ValidationError) as exc:
                llm_service.prompt(MESSAGES)

    assert exc.value.code == "errors.invalidParams"
