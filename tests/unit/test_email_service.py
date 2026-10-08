"""Unit tests for services.email_service.

``send_email`` is the fallback delivery channel used when a transactional
e-mail must not go through SMTP/SES — today it is what
``/user-admin/send-reset-email`` uses to deliver a password-reset link. It
talks to ODOO over XML-RPC in two steps: ``mail.mail create`` to store the
record, then ``mail.mail send`` to flush it through ODOO's outgoing mail
server.

What makes the service worth pinning down is that *a fault is not necessarily
a failure*. ODOO marshals replies with ``allow_none=False`` and
``mail.mail.send()`` returns ``None``, so a perfectly successful send surfaces
as an ``xmlrpc.client.Fault`` raised while encoding the reply, after the mail
already went out. The service therefore has to tell that benign fault apart
from a real one by its fault string, and has to treat a ``None`` reply (the
client's timeout signal) as "queued in ODOO" rather than as an error.

The caller turns a delivery error into a 200 with ``delivered=False``, which
never reaches the endpoint decorator's error logger, so every failure branch
also has to leave a warning behind. These tests assert both the outcome and
the log line.

``odoo_client.get_client`` is mocked throughout: no network is involved.
"""

import xmlrpc.client
from unittest.mock import MagicMock, patch

import pytest

from exception.validation_error import ValidationError
from services import email_service
from utils import status

_URL = "https://odoo.example.com/xmlrpc/2/"
_TO = ["fulano@example.com"]
_MANY_TO = ["fulano@example.com", "ciclano@example.com"]
_SUBJECT = "ZZTest: redefinicao de senha"
_HTML = "<p>ZZTest body</p>"
_MAIL_ID = 4242

# the benign fault ODOO raises when encoding the empty reply of mail.mail.send
_NONE_FAULT = xmlrpc.client.Fault(1, "cannot marshal None unless allow_none is enabled")
# anything else means the send itself went wrong
_REAL_FAULT = xmlrpc.client.Fault(2, "Mail delivery failed: invalid recipient")


@pytest.fixture(autouse=True)
def odoo_url():
    """Point the service at a configured (fake) ODOO instance."""
    with patch.object(email_service.Config, "ODOO_API_URL", _URL):
        yield


@pytest.fixture
def execute():
    """The ``execute`` callable ``get_client`` hands back, with a happy path set up.

    ``create`` returns a mail id and ``send`` reports success.
    """
    execute = MagicMock(name="execute")
    execute.side_effect = lambda model, action, *_: (
        _MAIL_ID if action == "create" else True
    )

    with patch.object(email_service.odoo_client, "get_client", return_value=execute):
        yield execute


@pytest.fixture
def no_client():
    """Make ``get_client`` report an unreachable ODOO."""
    with patch.object(email_service.odoo_client, "get_client", return_value=None):
        yield


@pytest.fixture
def backend_logger():
    """Capture the warnings the service emits."""
    with patch.object(email_service.logger, "backend_logger") as mock_logger:
        yield mock_logger


def _responses(mail_id=_MAIL_ID, send=True):
    """Build an ``execute`` side effect from the two replies ODOO gives.

    A ``Fault`` instance passed as ``mail_id``/``send`` is raised instead of
    returned, which is how ODOO reports both its benign and its real errors.
    """

    def side_effect(model, action, *_):
        assert model == "mail.mail"
        reply = mail_id if action == "create" else send
        if isinstance(reply, Exception):
            raise reply
        return reply

    return side_effect


class TestConfigurationGuard:
    """The service refuses to run when ODOO is not configured."""

    def test_missing_odoo_url_raises_a_configuration_error(self):
        """Without ODOO_API_URL there is nowhere to send: 400, not a crash."""
        with patch.object(email_service.Config, "ODOO_API_URL", None):
            with pytest.raises(ValidationError) as excinfo:
                email_service.send_email(to=_TO, subject=_SUBJECT, html=_HTML)

        assert excinfo.value.httpStatus == status.HTTP_400_BAD_REQUEST
        assert excinfo.value.code == "errors.businessRules"

    def test_missing_odoo_url_never_reaches_the_client(self):
        """The guard runs before any attempt to authenticate on ODOO."""
        with (
            patch.object(email_service.Config, "ODOO_API_URL", ""),
            patch.object(email_service.odoo_client, "get_client") as get_client,
        ):
            with pytest.raises(ValidationError):
                email_service.send_email(to=_TO, subject=_SUBJECT, html=_HTML)

        get_client.assert_not_called()


class TestSuccessfulDelivery:
    """The happy path and the payload handed to ODOO."""

    def test_returns_the_mail_record_id(self, execute):
        """The caller gets the id of the mail.mail record ODOO created."""
        assert (
            email_service.send_email(to=_TO, subject=_SUBJECT, html=_HTML) == _MAIL_ID
        )

    def test_creates_the_record_with_subject_body_and_recipients(self, execute):
        """create receives the e-mail fields under ODOO's own field names."""
        email_service.send_email(to=_TO, subject=_SUBJECT, html=_HTML)

        model, action, payload, options = execute.call_args_list[0].args
        assert (model, action) == ("mail.mail", "create")
        assert payload == [
            {"subject": _SUBJECT, "body_html": _HTML, "email_to": _TO[0]}
        ]
        assert options == {}

    def test_joins_several_recipients_into_one_field(self, execute):
        """ODOO takes email_to as a single comma-separated string."""
        email_service.send_email(to=_MANY_TO, subject=_SUBJECT, html=_HTML)

        payload = execute.call_args_list[0].args[2]
        assert payload[0]["email_to"] == "fulano@example.com,ciclano@example.com"

    def test_sends_the_created_record_asking_for_errors(self, execute):
        """send is called for that record with raise_exception, so faults surface."""
        email_service.send_email(to=_TO, subject=_SUBJECT, html=_HTML)

        model, action, payload, options = execute.call_args_list[1].args
        assert (model, action) == ("mail.mail", "send")
        assert payload == [[_MAIL_ID]]
        assert options == {"raise_exception": True}

    def test_a_successful_delivery_logs_nothing(self, execute, backend_logger):
        """Warnings are reserved for the branches that guess or fail."""
        email_service.send_email(to=_TO, subject=_SUBJECT, html=_HTML)

        backend_logger.warning.assert_not_called()


class TestUnreachableOdoo:
    """``get_client`` returning None means ODOO never answered."""

    def test_raises_a_delivery_error(self, no_client):
        """An unauthenticated client is a bad gateway, not a bad request."""
        with pytest.raises(ValidationError) as excinfo:
            email_service.send_email(to=_TO, subject=_SUBJECT, html=_HTML)

        assert excinfo.value.httpStatus == status.HTTP_502_BAD_GATEWAY

    def test_logs_the_recipients(self, no_client, backend_logger):
        """The warning names who did not get the e-mail."""
        with pytest.raises(ValidationError):
            email_service.send_email(to=_MANY_TO, subject=_SUBJECT, html=_HTML)

        backend_logger.warning.assert_called_once()
        assert (
            backend_logger.warning.call_args.args[1]
            == "fulano@example.com,ciclano@example.com"
        )


class TestCreateFailures:
    """Nothing was queued, so these are always errors."""

    def test_fault_while_creating_raises_a_delivery_error(self, execute):
        """A fault on create means no record exists: report a bad gateway."""
        execute.side_effect = _responses(mail_id=_REAL_FAULT)

        with pytest.raises(ValidationError) as excinfo:
            email_service.send_email(to=_TO, subject=_SUBJECT, html=_HTML)

        assert excinfo.value.httpStatus == status.HTTP_502_BAD_GATEWAY

    def test_fault_while_creating_keeps_the_original_as_cause(self, execute):
        """The XML-RPC fault is chained, so a traceback still shows it."""
        execute.side_effect = _responses(mail_id=_REAL_FAULT)

        with pytest.raises(ValidationError) as excinfo:
            email_service.send_email(to=_TO, subject=_SUBJECT, html=_HTML)

        assert excinfo.value.__cause__ is _REAL_FAULT

    def test_fault_while_creating_is_logged_with_the_step_and_fault(
        self, execute, backend_logger
    ):
        """The warning names the step, the recipients and the fault details."""
        execute.side_effect = _responses(mail_id=_REAL_FAULT)

        with pytest.raises(ValidationError):
            email_service.send_email(to=_TO, subject=_SUBJECT, html=_HTML)

        backend_logger.warning.assert_called_once()
        args = backend_logger.warning.call_args.args
        assert args[1] == "create"
        assert args[2] == _TO[0]
        assert args[3] == _REAL_FAULT.faultCode
        assert args[4] == _REAL_FAULT.faultString

    def test_fault_while_creating_never_attempts_a_send(self, execute):
        """There is no record to flush, so send is not called."""
        execute.side_effect = _responses(mail_id=_REAL_FAULT)

        with pytest.raises(ValidationError):
            email_service.send_email(to=_TO, subject=_SUBJECT, html=_HTML)

        assert [call.args[1] for call in execute.call_args_list] == ["create"]

    @pytest.mark.parametrize("mail_id", [None, 0, False])
    def test_falsy_create_reply_raises_a_delivery_error(self, execute, mail_id):
        """No usable id back (ODOO timed out) is reported as a failure."""
        execute.side_effect = _responses(mail_id=mail_id)

        with pytest.raises(ValidationError) as excinfo:
            email_service.send_email(to=_TO, subject=_SUBJECT, html=_HTML)

        assert excinfo.value.httpStatus == status.HTTP_502_BAD_GATEWAY

    def test_falsy_create_reply_is_logged_with_the_reply(self, execute, backend_logger):
        """The warning carries the reply, since the record may still exist."""
        execute.side_effect = _responses(mail_id=None)

        with pytest.raises(ValidationError):
            email_service.send_email(to=_TO, subject=_SUBJECT, html=_HTML)

        backend_logger.warning.assert_called_once()
        args = backend_logger.warning.call_args.args
        assert args[1] is None
        assert args[2] == _TO[0]


class TestSendFaults:
    """A fault on send may be ODOO failing to encode its own empty reply."""

    def test_marshal_none_fault_is_treated_as_a_successful_send(self, execute):
        """The mail went out; only the None reply failed to encode."""
        execute.side_effect = _responses(send=_NONE_FAULT)

        assert (
            email_service.send_email(to=_TO, subject=_SUBJECT, html=_HTML) == _MAIL_ID
        )

    def test_marshal_none_fault_is_not_logged(self, execute, backend_logger):
        """The benign fault is expected, so it leaves no warning behind."""
        execute.side_effect = _responses(send=_NONE_FAULT)

        email_service.send_email(to=_TO, subject=_SUBJECT, html=_HTML)

        backend_logger.warning.assert_not_called()

    def test_real_fault_raises_a_delivery_error(self, execute):
        """Any other fault string means the send itself failed."""
        execute.side_effect = _responses(send=_REAL_FAULT)

        with pytest.raises(ValidationError) as excinfo:
            email_service.send_email(to=_TO, subject=_SUBJECT, html=_HTML)

        assert excinfo.value.httpStatus == status.HTTP_502_BAD_GATEWAY
        assert excinfo.value.__cause__ is _REAL_FAULT

    def test_real_fault_is_logged_against_the_send_step(self, execute, backend_logger):
        """The warning distinguishes a send failure from a create failure."""
        execute.side_effect = _responses(send=_REAL_FAULT)

        with pytest.raises(ValidationError):
            email_service.send_email(to=_TO, subject=_SUBJECT, html=_HTML)

        backend_logger.warning.assert_called_once()
        assert backend_logger.warning.call_args.args[1] == "send"

    def test_fault_without_a_fault_string_is_treated_as_a_real_failure(self, execute):
        """A faultString of None must not be mistaken for the benign case."""
        execute.side_effect = _responses(send=xmlrpc.client.Fault(3, None))

        with pytest.raises(ValidationError) as excinfo:
            email_service.send_email(to=_TO, subject=_SUBJECT, html=_HTML)

        assert excinfo.value.httpStatus == status.HTTP_502_BAD_GATEWAY


class TestSendTimeout:
    """A ``None`` reply from send is the client's timeout signal."""

    def test_none_reply_still_reports_success(self, execute):
        """The record is queued in ODOO's cron, so the caller sees the mail id."""
        execute.side_effect = _responses(send=None)

        assert (
            email_service.send_email(to=_TO, subject=_SUBJECT, html=_HTML) == _MAIL_ID
        )

    def test_none_reply_is_logged_because_it_is_a_guess(self, execute, backend_logger):
        """The warning carries the mail id so the record can be looked up."""
        execute.side_effect = _responses(send=None)

        email_service.send_email(to=_TO, subject=_SUBJECT, html=_HTML)

        backend_logger.warning.assert_called_once()
        args = backend_logger.warning.call_args.args
        assert args[1] == _MAIL_ID
        assert args[2] == _TO[0]

    def test_falsy_but_not_none_reply_is_not_logged(self, execute, backend_logger):
        """Only ``None`` means "timed out"; ``False`` is a plain reply."""
        execute.side_effect = _responses(send=False)

        assert (
            email_service.send_email(to=_TO, subject=_SUBJECT, html=_HTML) == _MAIL_ID
        )
        backend_logger.warning.assert_not_called()
