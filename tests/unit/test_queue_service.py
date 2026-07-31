"""Unit tests for services.queue_service.check_sqs_message.

``check_sqs_message`` polls the ``backend`` SQS queue looking for a message
whose ``requestContext.requestId`` matches the requested id, deleting and
returning it when found. The SQS boundary (``utils.aws``) is mocked, so these
tests exercise the polling loop, payload parsing, deletion and the error/
validation branches without any AWS access.

The service is guarded by ``@has_permission(READ_BASIC_FEATURES)``. The
decorator resolves the caller from the JWT identity, so the JWT lookup and
``User`` model are patched to inject a fabricated user with the required (or
missing) role inside a Flask request context.
"""

import json
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from exception.authorization_error import AuthorizationError
from exception.validation_error import ValidationError
from mobile import app
from security.role import Role
from services import queue_service
from utils import status


@contextmanager
def acting_as(roles):
    """Run the block inside a request context authenticated as ``roles``.

    Patches the permission decorator's JWT identity lookup and ``User`` model
    so the decorated service resolves a fabricated user carrying ``roles``.
    """
    fake_user = MagicMock()
    fake_user.config = {"roles": roles}
    with app.test_request_context():
        with patch(
            "decorators.has_permission_decorator.get_jwt_identity", return_value=1
        ), patch("decorators.has_permission_decorator.User") as mock_user_cls:
            mock_user_cls.find.return_value = fake_user
            yield


def _message(request_id, response_payload=None, message_id="m1", receipt="r1"):
    """Build a raw SQS message dict with the given request id and payload."""
    body = {"requestContext": {"requestId": request_id}}
    if response_payload is not None:
        body["responsePayload"] = response_payload
    return {
        "MessageId": message_id,
        "ReceiptHandle": receipt,
        "Body": json.dumps(body),
        "Attributes": {"SentTimestamp": "1700000000"},
    }


def _mock_sqs(mock_aws, receive_side_effect=None, receive_return=None):
    """Wire ``mock_aws.get_client`` to a MagicMock SQS client and return it."""
    sqs = MagicMock()
    sqs.get_queue_url.return_value = {"QueueUrl": "http://queue.local/backend"}
    if receive_side_effect is not None:
        sqs.receive_message.side_effect = receive_side_effect
    else:
        sqs.receive_message.return_value = receive_return or {"Messages": []}
    mock_aws.get_client.return_value = sqs
    return sqs


class TestValidation:
    """Input validation and permission gating."""

    def test_missing_request_id_raises_400(self):
        """An empty request id is rejected before any SQS access."""
        with acting_as([Role.PRESCRIPTION_ANALYST.value]):
            with pytest.raises(ValidationError) as exc:
                queue_service.check_sqs_message(request_id="")

        assert exc.value.httpStatus == status.HTTP_400_BAD_REQUEST

    def test_permission_denied_without_basic_features(self):
        """A role lacking READ_BASIC_FEATURES cannot check the queue."""
        with acting_as([Role.DISPENSING_MANAGER.value]):
            with pytest.raises(AuthorizationError):
                queue_service.check_sqs_message(request_id="abc")


class TestMessageMatching:
    """Happy-path polling, matching, payload parsing and deletion."""

    @patch("services.queue_service.aws")
    def test_found_deletes_and_returns_parsed_payload(self, mock_aws):
        """A matching message is deleted and its string payload is JSON-decoded."""
        sqs = _mock_sqs(
            mock_aws,
            receive_return={
                "Messages": [_message("abc", response_payload='{"ok": true, "n": 5}')]
            },
        )

        with acting_as([Role.PRESCRIPTION_ANALYST.value]):
            result = queue_service.check_sqs_message(request_id="abc")

        assert result["found"] is True
        assert result["deleted"] is True
        assert result["response"] == {"ok": True, "n": 5}
        assert result["message_id"] == "m1"
        assert result["iterations"] == 1
        assert result["total_checked"] == 1
        sqs.delete_message.assert_called_once_with(
            QueueUrl="http://queue.local/backend", ReceiptHandle="r1"
        )

    @patch("services.queue_service.aws")
    def test_payload_already_dict_is_passed_through(self, mock_aws):
        """A responsePayload that is already a dict is returned unchanged."""
        _mock_sqs(
            mock_aws,
            receive_return={
                "Messages": [_message("abc", response_payload={"already": "dict"})]
            },
        )

        with acting_as([Role.PRESCRIPTION_ANALYST.value]):
            result = queue_service.check_sqs_message(request_id="abc")

        assert result["response"] == {"already": "dict"}

    @patch("services.queue_service.aws")
    def test_invalid_json_payload_kept_as_string(self, mock_aws):
        """A non-JSON string payload is left intact rather than raising."""
        _mock_sqs(
            mock_aws,
            receive_return={
                "Messages": [_message("abc", response_payload="not-json{")]
            },
        )

        with acting_as([Role.PRESCRIPTION_ANALYST.value]):
            result = queue_service.check_sqs_message(request_id="abc")

        assert result["found"] is True
        assert result["response"] == "not-json{"

    @patch("services.queue_service.aws")
    def test_match_found_in_later_batch(self, mock_aws):
        """Polling continues across batches until the matching id appears."""
        first_batch = {"Messages": [_message("other", message_id="m0", receipt="r0")]}
        second_batch = {"Messages": [_message("abc")]}
        _mock_sqs(mock_aws, receive_side_effect=[first_batch, second_batch])

        with acting_as([Role.PRESCRIPTION_ANALYST.value]):
            result = queue_service.check_sqs_message(request_id="abc")

        assert result["found"] is True
        assert result["iterations"] == 2
        # both batches were inspected before the match
        assert result["total_checked"] == 2

    @patch("services.queue_service.aws")
    def test_uses_configured_sqs_region(self, mock_aws):
        """The SQS client is created for the configured NiFi queue region."""
        _mock_sqs(mock_aws, receive_return={"Messages": [_message("abc")]})

        with acting_as([Role.PRESCRIPTION_ANALYST.value]):
            queue_service.check_sqs_message(request_id="abc")

        args, kwargs = mock_aws.get_client.call_args
        assert args[0] == "sqs"
        assert "region_name" in kwargs


class TestMessageNotFound:
    """Exhausting the queue without a match."""

    @patch("services.queue_service.aws")
    def test_empty_queue_returns_found_false(self, mock_aws):
        """An immediately empty queue short-circuits with nothing checked."""
        _mock_sqs(mock_aws, receive_return={"Messages": []})

        with acting_as([Role.PRESCRIPTION_ANALYST.value]):
            result = queue_service.check_sqs_message(request_id="abc")

        assert result["found"] is False
        assert result["checked_messages"] == 0

    @patch("services.queue_service.aws")
    def test_no_match_across_max_iterations(self, mock_aws):
        """Non-matching, always-full batches stop after max_iterations."""
        non_matching = {"Messages": [_message("other")]}
        sqs = _mock_sqs(mock_aws, receive_return=non_matching)

        with acting_as([Role.PRESCRIPTION_ANALYST.value]):
            result = queue_service.check_sqs_message(
                request_id="abc", max_iterations=3
            )

        assert result["found"] is False
        assert result["iterations"] == 3
        assert result["checked_messages"] == 3
        assert sqs.receive_message.call_count == 3
        sqs.delete_message.assert_not_called()


class TestErrorHandling:
    """SQS failures are surfaced as 500 ValidationErrors."""

    @patch("services.queue_service.aws")
    def test_get_queue_url_failure_raises_500(self, mock_aws):
        """A failure resolving the queue URL is a 500."""
        sqs = MagicMock()
        sqs.get_queue_url.side_effect = RuntimeError("boom")
        mock_aws.get_client.return_value = sqs

        with acting_as([Role.PRESCRIPTION_ANALYST.value]):
            with pytest.raises(ValidationError) as exc:
                queue_service.check_sqs_message(request_id="abc")

        assert exc.value.httpStatus == status.HTTP_500_INTERNAL_SERVER_ERROR

    @patch("services.queue_service.aws")
    def test_receive_message_failure_raises_500(self, mock_aws):
        """A failure reading messages is a 500."""
        sqs = _mock_sqs(mock_aws)
        sqs.receive_message.side_effect = RuntimeError("boom")

        with acting_as([Role.PRESCRIPTION_ANALYST.value]):
            with pytest.raises(ValidationError) as exc:
                queue_service.check_sqs_message(request_id="abc")

        assert exc.value.httpStatus == status.HTTP_500_INTERNAL_SERVER_ERROR

    @patch("services.queue_service.aws")
    def test_delete_message_failure_raises_500(self, mock_aws):
        """A failure deleting the matched message is a 500."""
        sqs = _mock_sqs(mock_aws, receive_return={"Messages": [_message("abc")]})
        sqs.delete_message.side_effect = RuntimeError("boom")

        with acting_as([Role.PRESCRIPTION_ANALYST.value]):
            with pytest.raises(ValidationError) as exc:
                queue_service.check_sqs_message(request_id="abc")

        assert exc.value.httpStatus == status.HTTP_500_INTERNAL_SERVER_ERROR
