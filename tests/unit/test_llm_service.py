"""Unit tests for services.llm_service.prompt.

``prompt`` is the single entry point the discharge summary screen uses to talk
to a language model. Which model answers is not decided by the caller: the
``summary-config`` global memory record names the provider, and ``prompt``
dispatches to the matching backend, each of which has its own request body,
its own Bedrock region and its own response shape to unwrap.

Both boundaries are mocked — the ``summary-config`` lookup (``db``) and the
Bedrock client (``utils.aws``) — so these tests cover the dispatch table, the
request bodies that are actually sent, the answer extraction of each provider
and the validation branches without a database or any AWS access.

The service is guarded by ``@has_permission(READ_DISCHARGE_SUMMARY)``. The
decorator resolves the caller from the JWT identity, so the JWT lookup and
``User`` model are patched to inject a fabricated user carrying (or missing)
the required role inside a Flask request context.
"""

import json
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from exception.authorization_error import AuthorizationError
from exception.validation_error import ValidationError
from mobile import app
from security.role import Role
from services import llm_service
from utils import status

MESSAGES = [
    {"role": "user", "content": "Resuma a internação"},
    {"role": "assistant", "content": "Claro"},
]


@contextmanager
def acting_as(roles):
    """Run the block inside a request context authenticated as ``roles``.

    Patches the permission decorator's JWT identity lookup and ``User`` model
    so the decorated service resolves a fabricated user carrying ``roles``.
    """
    fake_user = MagicMock()
    fake_user.config = {"roles": roles}
    with app.test_request_context():
        with (
            patch(
                "decorators.has_permission_decorator.get_jwt_identity", return_value=1
            ),
            patch("decorators.has_permission_decorator.User") as mock_user_cls,
        ):
            mock_user_cls.find.return_value = fake_user
            yield


@contextmanager
def summary_config(value):
    """Make the ``summary-config`` lookup return a record with ``value``.

    ``None`` stands for "no configuration stored".
    """
    record = None
    if value is not None:
        record = MagicMock()
        record.value = value

    with patch("services.llm_service.db") as mock_db:
        mock_db.session.query.return_value.filter.return_value.first.return_value = (
            record
        )
        yield


@contextmanager
def bedrock_answering(payload):
    """Make the Bedrock client return ``payload`` as the model response body"""
    client = MagicMock()
    body = MagicMock()
    body.read.return_value = json.dumps(payload).encode("utf-8")
    client.invoke_model.return_value = {"body": body}

    with patch("services.llm_service.aws") as mock_aws:
        mock_aws.get_client.return_value = client
        yield mock_aws, client


def _sent_body(client):
    """The request body the service handed to Bedrock, decoded"""
    return json.loads(client.invoke_model.call_args.kwargs["body"])


class TestGuards:
    """Permission gating, empty input and configuration validation."""

    def test_permission_denied_without_discharge_summary_role(self):
        """A role lacking READ_DISCHARGE_SUMMARY cannot prompt the model"""
        with acting_as([Role.VIEWER.value]):
            with pytest.raises(AuthorizationError):
                llm_service.prompt(MESSAGES)

    @pytest.mark.parametrize("messages", [None, []])
    def test_empty_messages_return_empty_answer(self, messages):
        """Nothing to ask means nothing to answer, and no provider is consulted"""
        with acting_as([Role.NAVIGATOR.value]):
            with patch("services.llm_service.aws") as mock_aws:
                assert llm_service.prompt(messages) == ""

        mock_aws.get_client.assert_not_called()

    def test_missing_configuration_is_rejected(self):
        """Without a summary-config record there is no provider to dispatch to"""
        with acting_as([Role.NAVIGATOR.value]), summary_config(None):
            with pytest.raises(ValidationError) as exc:
                llm_service.prompt(MESSAGES)

        assert exc.value.code == "errors.invalidParams"
        assert exc.value.httpStatus == status.HTTP_400_BAD_REQUEST

    def test_unknown_provider_is_rejected(self):
        """A provider outside the supported list is rejected before any call"""
        with (
            acting_as([Role.NAVIGATOR.value]),
            summary_config({"provider": "some-other-llm"}),
        ):
            with pytest.raises(ValidationError) as exc:
                llm_service.prompt(MESSAGES)

        assert exc.value.code == "errors.invalidParams"

    @pytest.mark.parametrize(
        "provider,message",
        [("openai_azure", "OpenAi"), ("maritaca", "Maritaca")],
    )
    def test_accepted_but_unimplemented_providers(self, provider, message):
        """Configurable providers that have no backend yet report it explicitly"""
        with acting_as([Role.NAVIGATOR.value]), summary_config({"provider": provider}):
            with pytest.raises(ValidationError) as exc:
                llm_service.prompt(MESSAGES)

        assert exc.value.code == "errors.invalidModule"
        assert message in str(exc.value)


class TestClaudeProvider:
    """Dispatch to the Anthropic models hosted on Bedrock."""

    def test_returns_the_first_content_block(self):
        """The answer is the text of the first content block of the response"""
        with (
            acting_as([Role.NAVIGATOR.value]),
            summary_config({"provider": "claude"}),
            bedrock_answering(
                {"content": [{"text": "Paciente estável"}, {"text": "ignorado"}]}
            ),
        ):
            result = llm_service.prompt(MESSAGES)

        assert result == {"answer": "Paciente estável"}

    def test_sends_the_messages_and_the_anthropic_version(self):
        """The conversation is forwarded verbatim with the Bedrock API version"""
        with (
            acting_as([Role.NAVIGATOR.value]),
            summary_config({"provider": "claude"}),
            bedrock_answering({"content": [{"text": "ok"}]}) as (mock_aws, client),
        ):
            llm_service.prompt(MESSAGES)

        body = _sent_body(client)
        assert body["messages"] == MESSAGES
        assert body["max_tokens"] == 1024
        assert body["anthropic_version"] == "bedrock-2023-05-31"
        assert client.invoke_model.call_args.kwargs["contentType"] == "application/json"
        mock_aws.get_client.assert_called_once_with(
            "bedrock-runtime", region_name="us-east-1"
        )


class TestGptOssProvider:
    """Dispatch to the open-weights GPT model hosted on Bedrock."""

    def test_returns_the_first_choice_message(self):
        """The answer is the content of the first choice of the response"""
        with (
            acting_as([Role.NAVIGATOR.value]),
            summary_config({"provider": "gpt_oss"}),
            bedrock_answering(
                {"choices": [{"message": {"content": "Alta em bom estado"}}]}
            ),
        ):
            result = llm_service.prompt(MESSAGES)

        assert result == {"answer": "Alta em bom estado"}

    def test_strips_the_reasoning_block(self):
        """The model's chain of thought is removed before the answer is returned"""
        answer = "<reasoning>pensando\nem varias linhas</reasoning>Conduta mantida"
        with (
            acting_as([Role.NAVIGATOR.value]),
            summary_config({"provider": "gpt_oss"}),
            bedrock_answering({"choices": [{"message": {"content": answer}}]}),
        ):
            result = llm_service.prompt(MESSAGES)

        assert result == {"answer": "Conduta mantida"}

    def test_strips_every_reasoning_block(self):
        """More than one reasoning block is removed, not only the first"""
        answer = "<reasoning>a</reasoning>parte 1<reasoning>b</reasoning>parte 2"
        with (
            acting_as([Role.NAVIGATOR.value]),
            summary_config({"provider": "gpt_oss"}),
            bedrock_answering({"choices": [{"message": {"content": answer}}]}),
        ):
            result = llm_service.prompt(MESSAGES)

        assert result == {"answer": "parte 1parte 2"}

    def test_sends_the_messages_to_the_gpt_oss_model(self):
        """The conversation is forwarded to the gpt-oss model in us-east-1"""
        with (
            acting_as([Role.NAVIGATOR.value]),
            summary_config({"provider": "gpt_oss"}),
            bedrock_answering({"choices": [{"message": {"content": "ok"}}]}) as (
                mock_aws,
                client,
            ),
        ):
            llm_service.prompt(MESSAGES)

        body = _sent_body(client)
        assert body["messages"] == MESSAGES
        assert body["max_tokens"] == 1024
        # the Anthropic-only field must not leak into the other providers
        assert "anthropic_version" not in body
        assert "gpt-oss" in client.invoke_model.call_args.kwargs["modelId"]
        mock_aws.get_client.assert_called_once_with(
            "bedrock-runtime", region_name="us-east-1"
        )


class TestLlamaProvider:
    """Dispatch to the Llama model, which takes a flat prompt string."""

    def test_returns_the_generation(self):
        """The answer is the ``generation`` field of the response"""
        with (
            acting_as([Role.NAVIGATOR.value]),
            summary_config({"provider": "llama"}),
            bedrock_answering({"generation": "Resumo gerado"}),
        ):
            result = llm_service.prompt(MESSAGES)

        assert result == {"answer": "Resumo gerado"}

    def test_renders_the_conversation_with_llama_header_tokens(self):
        """Each message becomes a header/content pair, ending on the assistant turn"""
        with (
            acting_as([Role.NAVIGATOR.value]),
            summary_config({"provider": "llama"}),
            bedrock_answering({"generation": "ok"}) as (mock_aws, client),
        ):
            llm_service.prompt(MESSAGES)

        prompt = _sent_body(client)["prompt"]

        assert prompt == (
            "<|begin_of_text|>"
            "<|start_header_id|>user<|end_header_id|>\n"
            "Resuma a internação<|eot_id|>\n"
            "<|start_header_id|>assistant<|end_header_id|>\n"
            "Claro<|eot_id|>\n"
            "<|start_header_id|>assistant<|end_header_id|>"
        )
        # Llama is served from a different region than the other providers
        mock_aws.get_client.assert_called_once_with(
            "bedrock-runtime", region_name="us-west-2"
        )

    def test_sends_the_generation_parameters(self):
        """The sampling parameters travel with the prompt"""
        with (
            acting_as([Role.NAVIGATOR.value]),
            summary_config({"provider": "llama"}),
            bedrock_answering({"generation": "ok"}) as (_, client),
        ):
            llm_service.prompt(MESSAGES)

        body = _sent_body(client)
        assert body["max_gen_len"] == 1024
        assert body["temperature"] == 0.5
        assert body["top_p"] == 0.9
