"""Unit tests for the shared ODOO XML-RPC client (services.odoo_client).

``get_client`` is the single door to ODOO: the e-mail service, the support
service and the digital-signature service all go through it. It authenticates
once and hands back an ``execute`` callable that wraps ``execute_kw``.

Its contract is mostly about what happens when ODOO does not answer, because
that is what the callers branch on:

* a timeout while authenticating makes ``get_client`` return ``None`` instead
  of raising — ``email_service`` turns that into a delivery error;
* a timeout inside ``execute`` makes *that call* return ``None`` while the
  client stays usable — ``email_service`` reads a ``None`` reply as "the record
  may still be queued in ODOO";
* anything else, in particular an ``xmlrpc.client.Fault``, is left to the
  caller, which inspects the fault string.

Every failure is logged with the ``context`` the caller passed, so a warning in
CloudWatch names the service that hit ODOO.

Both proxies and the socket are mocked: no network is involved.
"""

import http.client
import socket
import xmlrpc.client
from unittest.mock import MagicMock, patch

import pytest

from services import odoo_client

_URL = "https://odoo.example.com/xmlrpc/2/"
_DB = "zztest-db"
_USER = "fulano@example.com"
_KEY = "zztest-api-key"
_UID = 42


@pytest.fixture(autouse=True)
def odoo_config():
    """Point the client at a fake ODOO instance."""
    with (
        patch.object(odoo_client.Config, "ODOO_API_URL", _URL),
        patch.object(odoo_client.Config, "ODOO_API_DB", _DB),
        patch.object(odoo_client.Config, "ODOO_API_USER", _USER),
        patch.object(odoo_client.Config, "ODOO_API_KEY", _KEY),
    ):
        yield


@pytest.fixture
def server_proxy():
    """Replace ServerProxy: the first call returns ``common``, the second ``object``."""
    common = MagicMock(name="common")
    common.authenticate.return_value = _UID
    models = MagicMock(name="object")

    with patch("xmlrpc.client.ServerProxy") as proxy:
        proxy.side_effect = [common, models]
        proxy.common = common
        proxy.models = models
        yield proxy


@pytest.fixture
def backend_logger():
    """Capture the warnings the client emits."""
    with patch.object(odoo_client.logger, "backend_logger") as mock_logger:
        yield mock_logger


class TestGetClient:
    """Authentication and proxy construction."""

    def test_both_endpoints_are_built_from_the_configured_url(self, server_proxy):
        """The common and object endpoints hang off ODOO_API_URL."""
        odoo_client.get_client()

        urls = [call.args[0] for call in server_proxy.call_args_list]
        assert urls == [_URL + "common", _URL + "object"]

    def test_both_proxies_share_one_timeout_transport(self, server_proxy):
        """A single transport is built, so both endpoints get the 15s timeout."""
        odoo_client.get_client()

        transports = [call.kwargs["transport"] for call in server_proxy.call_args_list]
        assert len(transports) == 2
        assert transports[0] is transports[1]
        assert isinstance(transports[0], odoo_client.TimeoutTransport)
        assert transports[0].timeout == 15

    def test_authenticates_with_the_configured_credentials(self, server_proxy):
        """The database, user and api key come from the configuration."""
        odoo_client.get_client()

        server_proxy.common.authenticate.assert_called_once_with(_DB, _USER, _KEY, {})

    def test_returns_a_callable_when_authentication_succeeds(self, server_proxy):
        """A usable client is an ``execute`` callable, not the proxy itself."""
        assert callable(odoo_client.get_client())

    def test_timeout_while_authenticating_returns_none(
        self, server_proxy, backend_logger
    ):
        """A silent ODOO is reported as "no client", never as an exception."""
        server_proxy.common.authenticate.side_effect = socket.timeout

        assert odoo_client.get_client(context="email service") is None

        backend_logger.warning.assert_called_once()
        assert backend_logger.warning.call_args.args[1] == "email service"

    def test_timeout_while_authenticating_skips_the_object_proxy(self, server_proxy):
        """Nothing else is opened once authentication timed out."""
        server_proxy.common.authenticate.side_effect = socket.timeout

        odoo_client.get_client()

        assert server_proxy.call_count == 1

    def test_the_default_context_names_the_client(self, server_proxy, backend_logger):
        """Callers that pass no context still produce an identifiable warning."""
        server_proxy.common.authenticate.side_effect = socket.timeout

        odoo_client.get_client()

        assert backend_logger.warning.call_args.args[1] == "odoo client"

    def test_an_authentication_fault_is_not_swallowed(self, server_proxy):
        """Only timeouts are absorbed; a fault is an ODOO answer and must surface."""
        server_proxy.common.authenticate.side_effect = xmlrpc.client.Fault(
            2, "AccessDenied"
        )

        with pytest.raises(xmlrpc.client.Fault):
            odoo_client.get_client()


class TestExecute:
    """The callable returned by get_client."""

    def test_forwards_the_call_to_execute_kw(self, server_proxy):
        """The authenticated uid and the api key are added to the caller's arguments."""
        execute = odoo_client.get_client()

        execute("mail.mail", "create", [{"subject": "zztest"}], {"context": {}})

        server_proxy.models.execute_kw.assert_called_once_with(
            _DB,
            _UID,
            _KEY,
            "mail.mail",
            "create",
            [{"subject": "zztest"}],
            {"context": {}},
        )

    def test_returns_the_odoo_reply(self, server_proxy):
        """Whatever ODOO answers is handed back untouched."""
        server_proxy.models.execute_kw.return_value = [1, 2, 3]

        assert odoo_client.get_client()("mail.mail", "search", [[]], {}) == [1, 2, 3]

    def test_timeout_returns_none(self, server_proxy, backend_logger):
        """A timed out call reports ``None`` so the caller can decide what it means."""
        server_proxy.models.execute_kw.side_effect = socket.timeout

        result = odoo_client.get_client(context="support service")(
            "mail.mail", "send", [[1]], {}
        )

        assert result is None
        backend_logger.warning.assert_called_once()
        assert backend_logger.warning.call_args.args[1] == "support service"

    def test_the_client_survives_a_timed_out_call(self, server_proxy):
        """One timeout does not invalidate the client: the next call still runs."""
        server_proxy.models.execute_kw.side_effect = [socket.timeout, "ok"]
        execute = odoo_client.get_client()

        assert execute("mail.mail", "send", [[1]], {}) is None
        assert execute("mail.mail", "send", [[1]], {}) == "ok"

    def test_a_fault_is_not_swallowed(self, server_proxy):
        """Callers inspect the fault string, so it must reach them."""
        server_proxy.models.execute_kw.side_effect = xmlrpc.client.Fault(1, "boom")

        with pytest.raises(xmlrpc.client.Fault):
            odoo_client.get_client()("mail.mail", "create", [{}], {})


class TestTimeoutTransport:
    """The transport that puts a deadline on the XML-RPC socket."""

    def test_is_an_xmlrpc_transport(self):
        """It only overrides how the connection is made."""
        assert isinstance(odoo_client.TimeoutTransport(timeout=1), xmlrpc.client.Transport)

    def test_connections_carry_the_configured_timeout(self):
        """Without this the request would hang on the default socket timeout."""
        transport = odoo_client.TimeoutTransport(timeout=7)

        connection = transport.make_connection("odoo.example.com")

        assert isinstance(connection, http.client.HTTPConnection)
        assert connection.timeout == 7
        assert connection.host == "odoo.example.com"
