"""Unit tests for utils.network_utils (client IP extraction / validation)"""

import pytest
from flask import Flask

from utils import network_utils


@pytest.fixture
def app():
    """A bare Flask app used only to build request contexts."""
    return Flask(__name__)


class TestIsValidIp:
    """Teste network_utils - is_valid_ip"""

    @pytest.mark.parametrize(
        "ip",
        [
            "192.168.0.1",
            "8.8.8.8",
            "255.255.255.255",
            "0.0.0.0",
            "::1",
            "2001:db8::1",
        ],
    )
    def test_valid_addresses(self, ip):
        """Well-formed IPv4 and IPv6 addresses are accepted"""
        assert network_utils.is_valid_ip(ip) is True

    @pytest.mark.parametrize(
        "ip",
        [
            "",
            "not-an-ip",
            "999.999.999.999",
            "192.168.0",
            "192.168.0.1.5",
            "12345",
            " 8.8.8.8",
        ],
    )
    def test_invalid_addresses(self, ip):
        """Malformed values are rejected"""
        assert network_utils.is_valid_ip(ip) is False


class TestGetClientIpFromRequest:
    """Teste network_utils - get_client_ip_from_request"""

    def test_uses_first_ip_from_x_forwarded_for(self, app):
        """The first (original client) IP in X-Forwarded-For wins"""
        with app.test_request_context(
            headers={"X-Forwarded-For": "203.0.113.7, 70.41.3.18, 150.172.238.178"}
        ):
            assert network_utils.get_client_ip_from_request() == "203.0.113.7"

    def test_x_forwarded_for_is_trimmed(self, app):
        """Surrounding whitespace on the first entry is stripped"""
        with app.test_request_context(
            headers={"X-Forwarded-For": "  203.0.113.7  , 70.41.3.18"}
        ):
            assert network_utils.get_client_ip_from_request() == "203.0.113.7"

    def test_falls_back_to_alternative_header(self, app):
        """When X-Forwarded-For is absent, alternative headers are consulted"""
        with app.test_request_context(headers={"X-Real-IP": "198.51.100.23"}):
            assert network_utils.get_client_ip_from_request() == "198.51.100.23"

    def test_cloudflare_header_supported(self, app):
        """CF-Connecting-IP is honored as an alternative header"""
        with app.test_request_context(headers={"CF-Connecting-IP": "198.51.100.9"}):
            assert network_utils.get_client_ip_from_request() == "198.51.100.9"

    def test_invalid_forwarded_for_falls_through(self, app):
        """An invalid X-Forwarded-For entry is ignored in favor of a valid header"""
        with app.test_request_context(
            headers={"X-Forwarded-For": "garbage", "X-Real-IP": "198.51.100.23"}
        ):
            assert network_utils.get_client_ip_from_request() == "198.51.100.23"

    def test_falls_back_to_remote_addr(self, app):
        """With no forwarding headers, remote_addr is returned"""
        with app.test_request_context(environ_base={"REMOTE_ADDR": "192.0.2.55"}):
            assert network_utils.get_client_ip_from_request() == "192.0.2.55"

    def test_forwarded_for_preferred_over_remote_addr(self, app):
        """A valid X-Forwarded-For takes precedence over remote_addr"""
        with app.test_request_context(
            headers={"X-Forwarded-For": "203.0.113.7"},
            environ_base={"REMOTE_ADDR": "192.0.2.55"},
        ):
            assert network_utils.get_client_ip_from_request() == "203.0.113.7"


class TestGetClientIpWithValidation:
    """Teste network_utils - get_client_ip_with_validation"""

    def test_returns_normalized_public_ip(self, app):
        """A valid public IP is returned normalized"""
        with app.test_request_context(headers={"X-Forwarded-For": "203.0.113.7"}):
            assert network_utils.get_client_ip_with_validation() == "203.0.113.7"

    def test_ipv6_is_normalized(self, app):
        """An IPv6 address is returned in its canonical compressed form"""
        with app.test_request_context(headers={"X-Forwarded-For": "2001:0db8::0001"}):
            assert network_utils.get_client_ip_with_validation() == "2001:db8::1"

    def test_private_ip_is_still_returned(self, app):
        """Private IPs are currently allowed and returned unchanged"""
        with app.test_request_context(
            environ_base={"REMOTE_ADDR": "10.0.0.5"}
        ):
            assert network_utils.get_client_ip_with_validation() == "10.0.0.5"

    def test_invalid_ip_returns_original_value(self, app):
        """If the resolved value is not a valid IP, it is returned as-is"""
        with app.test_request_context(
            environ_base={"REMOTE_ADDR": "not-an-ip"}
        ):
            assert network_utils.get_client_ip_with_validation() == "not-an-ip"
