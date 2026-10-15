"""Unit tests: how the patient-name strategies degrade when the upstream fails.

Patient names never live in the NoHarm database; every screen that shows one
asks the hospital's name service (an internal NoHarm API, an OAuth-protected
external API, a key-protected proxy or a DynamoDB table). Those services go
down, time out and answer with errors, and none of that may break the screen
that asked: the contract every strategy keeps is that

* a failed lookup still answers, with the ``status: "error"`` placeholder
  ("Paciente <id>") for the patient it could not resolve;
* a multiple-names lookup answers for *every* id it was given, in the shape
  above, whatever part of the batch the upstream lost;
* the failure is logged as a warning (an error for DynamoDB) instead of raised;
* a search that fails comes back empty, and a plain "no results" (404) from
  the internal service is not logged as a failure.

The happy paths are covered by test_name_service_strategies.py; these tests
drive the failure branches of each strategy with ``requests`` and ``aws``
patched, so no network or database is used.
"""

from unittest.mock import MagicMock, Mock, patch

import pytest
import requests

from services.name_service import (
    DynamoDBNameService,
    ExternalNameService,
    GetNameProxyService,
    NameServiceStrategy,
    NHInternalNameService,
)

PATIENT_ID = 12345


def _response(status_code, payload=None):
    """Build a fake ``requests`` response."""
    response = Mock()
    response.status_code = status_code
    response.json.return_value = payload
    return response


def _assert_placeholder(result, id_patient=PATIENT_ID):
    """Assert ``result`` is the standard not-resolved placeholder."""
    assert result == {
        "status": "error",
        "idPatient": id_patient,
        "name": f"Paciente {id_patient}",
    }


@pytest.fixture
def mock_logger():
    """Patch the module logger so warnings can be asserted."""
    with patch("services.name_service.logger") as logger:
        yield logger.backend_logger


class TestNHInternalFailures:
    """NoHarm internal name service (JWT signed locally)."""

    @pytest.fixture
    def service(self):
        """An internal service with a fixed signing secret."""
        config = {
            "getname": {
                "internal": True,
                "url": "https://names.example.com/",
                "token": {"url": "internal", "params": {"client_secret": "s3cr3t"}},
                "params": {"schema": "test_schema"},
            }
        }
        return NHInternalNameService(config, "test_schema")

    @patch("services.name_service.requests.get")
    def test_single_name_http_error_returns_placeholder(
        self, mock_get, service, mock_logger
    ):
        """A non-200 answer yields the placeholder and a warning."""
        mock_get.return_value = _response(500)

        _assert_placeholder(service.get_single_name(PATIENT_ID))
        assert mock_logger.warning.called

    @patch("services.name_service.requests.get")
    def test_single_name_network_error_returns_placeholder(
        self, mock_get, service, mock_logger
    ):
        """A connection error is swallowed into the placeholder."""
        mock_get.side_effect = requests.exceptions.ConnectionError("refused")

        _assert_placeholder(service.get_single_name(PATIENT_ID))
        assert mock_logger.warning.called

    @patch("services.name_service.requests.get")
    def test_single_name_signs_a_bearer_token(self, mock_get, service):
        """The request carries a locally signed JWT and hits patient-name/<id>."""
        mock_get.return_value = _response(500)

        service.get_single_name(PATIENT_ID)

        args, kwargs = mock_get.call_args
        assert args[0] == f"https://names.example.com/patient-name/{PATIENT_ID}"
        assert kwargs["headers"]["Authorization"].startswith("Bearer ey")

    @patch("services.name_service.requests.post")
    def test_multiple_names_http_error_returns_a_placeholder_per_id(
        self, mock_post, service, mock_logger
    ):
        """A non-200 batch still answers for every id, in order."""
        mock_post.return_value = _response(503)

        result = service.get_multiple_names([1, 2, 3])

        assert [r["idPatient"] for r in result] == [1, 2, 3]
        assert all(r["status"] == "error" for r in result)
        assert mock_logger.warning.called

    @patch("services.name_service.requests.post")
    def test_multiple_names_timeout_returns_a_placeholder_per_id(
        self, mock_post, service, mock_logger
    ):
        """A timeout still answers for every id."""
        mock_post.side_effect = requests.exceptions.Timeout("slow")

        result = service.get_multiple_names([1, 2])

        assert [r["idPatient"] for r in result] == [1, 2]
        assert all(r["status"] == "error" for r in result)
        assert mock_logger.warning.called

    @patch("services.name_service.requests.post")
    def test_multiple_names_are_html_escaped(self, mock_post, service):
        """Names coming from upstream are escaped before reaching the UI."""
        mock_post.return_value = _response(
            200, [{"idPatient": 1, "name": "<b>Fulano</b>"}]
        )

        result = service.get_multiple_names([1])

        assert result[0]["name"] == "&lt;b&gt;Fulano&lt;/b&gt;"

    @patch("services.name_service.requests.get")
    def test_search_not_found_is_empty_and_silent(self, mock_get, service, mock_logger):
        """A 404 means no match: empty result, nothing logged."""
        mock_get.return_value = _response(404)

        assert service.search_by_name("Fulano") == []
        mock_logger.warning.assert_not_called()

    @patch("services.name_service.requests.get")
    def test_search_server_error_is_empty_and_logged(
        self, mock_get, service, mock_logger
    ):
        """Any other non-200 answer is empty and logged."""
        mock_get.return_value = _response(500)

        assert service.search_by_name("Fulano") == []
        assert mock_logger.warning.called

    @patch("services.name_service.requests.get")
    def test_search_network_error_is_empty_and_logged(
        self, mock_get, service, mock_logger
    ):
        """A connection error during search is empty and logged."""
        mock_get.side_effect = requests.exceptions.ConnectionError("refused")

        assert service.search_by_name("Fulano") == []
        assert mock_logger.warning.called

    @patch("services.name_service.requests.get")
    def test_search_term_is_url_quoted(self, mock_get, service):
        """A term with slashes or spaces cannot change the upstream path."""
        mock_get.return_value = _response(404)

        service.search_by_name("Fulano/../admin de Tal")

        url = mock_get.call_args.args[0]
        assert url == (
            "https://names.example.com/search-name/Fulano%2F..%2Fadmin%20de%20Tal"
        )

    @patch("services.name_service.requests.get")
    def test_search_results_are_capped_and_sorted(self, mock_get, service):
        """At most 150 results are kept, sorted by name."""
        results = [
            {
                "name": f"Paciente Teste {i:03d}",
                "idPatient": i,
                "dtnascimento": "2000-01-01",
                "cpf": "000.000.000-00",
            }
            for i in range(200, 0, -1)
        ]
        mock_get.return_value = _response(200, {"results": results})

        found = service.search_by_name("Paciente")

        assert len(found) == 150
        assert [r["name"] for r in found] == sorted(r["name"] for r in found)


class TestExternalFailures:
    """External name service (OAuth token)."""

    @pytest.fixture
    def service(self):
        """An external service whose token call is configured."""
        config = {
            "getname": {
                "url": "https://hospital.example.com/names",
                "authPrefix": "Bearer ",
                "token": {
                    "url": "https://hospital.example.com/token",
                    "params": {"client_id": "x"},
                },
                "params": {},
            }
        }
        return ExternalNameService(config, "test_schema")

    @pytest.fixture
    def token_ok(self):
        """Patch the token endpoint to always succeed."""
        with patch("services.name_service.requests.post") as mock_post:
            mock_post.return_value = _response(200, {"access_token": "tok"})
            yield mock_post

    @patch("services.name_service.requests.get")
    def test_single_name_empty_data_returns_placeholder(
        self, mock_get, service, token_ok
    ):
        """A 200 answer with no patient is the placeholder."""
        mock_get.return_value = _response(200, {"data": []})

        _assert_placeholder(service.get_single_name(PATIENT_ID))

    @patch("services.name_service.requests.get")
    def test_single_name_http_error_returns_placeholder(
        self, mock_get, service, token_ok, mock_logger
    ):
        """A non-200 answer is the placeholder, logged."""
        mock_get.return_value = _response(502)

        _assert_placeholder(service.get_single_name(PATIENT_ID))
        assert mock_logger.warning.called

    @patch("services.name_service.requests.get")
    def test_single_name_network_error_returns_placeholder(
        self, mock_get, service, token_ok, mock_logger
    ):
        """A connection error is the placeholder, logged."""
        mock_get.side_effect = requests.exceptions.ConnectionError("refused")

        _assert_placeholder(service.get_single_name(PATIENT_ID))
        assert mock_logger.warning.called

    @patch("services.name_service.requests.get")
    def test_single_name_sends_the_auth_prefix(self, mock_get, service, token_ok):
        """The token is sent with the configured prefix."""
        mock_get.return_value = _response(
            200, {"data": [{"idPatient": PATIENT_ID, "name": "Fulano Beltrano"}]}
        )

        result = service.get_single_name(PATIENT_ID)

        assert result["status"] == "success"
        assert result["name"] == "Fulano Beltrano"
        assert mock_get.call_args.kwargs["headers"]["Authorization"] == "Bearer tok"

    @patch("services.name_service.requests.get")
    def test_multiple_names_partial_answer_fills_the_gaps(
        self, mock_get, service, token_ok
    ):
        """Ids the upstream left out come back as placeholders."""
        mock_get.return_value = _response(
            200, {"data": [{"idPatient": 2, "name": "Ciclano de Tal"}]}
        )

        result = service.get_multiple_names([1, 2, 3])

        by_id = {r["idPatient"]: r for r in result}
        assert set(by_id) == {1, 2, 3}
        assert by_id[2]["status"] == "success"
        assert by_id[1]["status"] == "error"
        assert by_id[3]["status"] == "error"
        assert mock_get.call_args.kwargs["params"]["cd_paciente"] == "1 2 3"

    @patch("services.name_service.requests.get")
    def test_multiple_names_http_error_returns_a_placeholder_per_id(
        self, mock_get, service, token_ok, mock_logger
    ):
        """A non-200 batch answers every id with a placeholder."""
        mock_get.return_value = _response(500)

        result = service.get_multiple_names([1, 2])

        assert [r["idPatient"] for r in result] == [1, 2]
        assert all(r["status"] == "error" for r in result)
        assert mock_logger.warning.called

    @patch("services.name_service.requests.get")
    def test_multiple_names_network_error_returns_a_placeholder_per_id(
        self, mock_get, service, token_ok, mock_logger
    ):
        """A connection error answers every id with a placeholder."""
        mock_get.side_effect = requests.exceptions.ConnectionError("refused")

        result = service.get_multiple_names([1, 2])

        assert all(r["status"] == "error" for r in result)
        assert len(result) == 2
        assert mock_logger.warning.called

    def test_search_is_not_supported(self, service, mock_logger):
        """External services cannot search: empty, logged."""
        assert service.search_by_name("Fulano") == []
        assert mock_logger.warning.called


class TestProxyFailures:
    """Proxy name service (X-API-Key, no token)."""

    @pytest.fixture
    def service(self):
        """A proxy service with a fixed API key."""
        config = {
            "getname": {
                "type": "getname-proxy",
                "url": "https://proxy.example.com/patients",
                "xapikey": "key",
                "params": {},
            }
        }
        return GetNameProxyService(config, "test_schema")

    @patch("services.name_service.requests.get")
    def test_single_name_http_error_returns_placeholder(
        self, mock_get, service, mock_logger
    ):
        """A non-200 answer is the placeholder, logged."""
        mock_get.return_value = _response(500)

        _assert_placeholder(service.get_single_name(PATIENT_ID))
        assert mock_logger.warning.called

    @patch("services.name_service.requests.get")
    def test_multiple_names_http_error_returns_a_placeholder_per_id(
        self, mock_get, service, mock_logger
    ):
        """A non-200 batch answers every id with a placeholder."""
        mock_get.return_value = _response(500)

        result = service.get_multiple_names([1, 2])

        assert [r["idPatient"] for r in result] == [1, 2]
        assert all(r["status"] == "error" for r in result)
        assert mock_logger.warning.called

    @patch("services.name_service.requests.get")
    def test_multiple_names_network_error_returns_a_placeholder_per_id(
        self, mock_get, service, mock_logger
    ):
        """A connection error answers every id with a placeholder."""
        mock_get.side_effect = requests.exceptions.Timeout("slow")

        result = service.get_multiple_names([1, 2])

        assert all(r["status"] == "error" for r in result)
        assert len(result) == 2
        assert mock_logger.warning.called


class TestDynamoDBFailures:
    """DynamoDB name service."""

    @pytest.fixture
    def service(self):
        """A DynamoDB service reading from a fake table."""
        config = {
            "getname": {"token": {"url": "dy:names-table", "params": {}}, "params": {}}
        }
        return DynamoDBNameService(config, "test_schema")

    @patch("services.name_service.aws")
    def test_single_name_error_returns_placeholder(
        self, mock_aws, service, mock_logger
    ):
        """A DynamoDB exception is the placeholder, logged as an error."""
        mock_aws.get_resource.return_value.Table.return_value.get_item.side_effect = (
            Exception("throttled")
        )

        _assert_placeholder(service.get_single_name(PATIENT_ID))
        assert mock_logger.error.called

    @patch("services.name_service.aws")
    def test_multiple_names_empty_list_skips_dynamodb(self, mock_aws, service):
        """No ids, no request."""
        assert service.get_multiple_names([]) == []
        mock_aws.get_resource.assert_not_called()

    @patch("services.name_service.aws")
    def test_multiple_names_error_returns_a_placeholder_per_id(
        self, mock_aws, service, mock_logger
    ):
        """A batch_get_item exception answers every id with a placeholder."""
        mock_aws.get_resource.return_value.batch_get_item.side_effect = Exception(
            "throttled"
        )

        result = service.get_multiple_names([1, 2])

        assert [r["idPatient"] for r in result] == [1, 2]
        assert all(r["status"] == "error" for r in result)
        assert mock_logger.error.called

    @patch("services.name_service.aws")
    def test_multiple_names_retries_unprocessed_keys(self, mock_aws, service):
        """Keys DynamoDB leaves unprocessed are requested again."""
        dynamodb = MagicMock()
        dynamodb.batch_get_item.side_effect = [
            {
                "Responses": {
                    "names-table": [{"schema_fkpessoa": "1", "nome": "Fulano"}]
                },
                "UnprocessedKeys": {
                    "names-table": {"Keys": [{"schema_fkpessoa": "2"}]}
                },
            },
            {
                "Responses": {
                    "names-table": [{"schema_fkpessoa": "2", "nome": "Ciclano"}]
                },
            },
        ]
        mock_aws.get_resource.return_value = dynamodb

        result = service.get_multiple_names([1, 2])

        assert dynamodb.batch_get_item.call_count == 2
        assert [r["name"] for r in result] == ["Fulano", "Ciclano"]
        assert all(r["status"] == "success" for r in result)


class TestEscape:
    """The shared escaping helper."""

    def test_none_becomes_empty_string(self):
        """A missing value from upstream renders as an empty string."""
        assert NameServiceStrategy._escape_str(None) == ""
