"""Unit tests for name service strategies"""

from unittest.mock import MagicMock, Mock, patch

import pytest

from services.name_service import (
    DynamoDBNameService,
    ExternalNameService,
    NameServiceFactory,
    NHInternalNameService,
)


class TestDynamoDBNameService:
    """Test DynamoDB name service strategy"""

    @pytest.fixture
    def config(self):
        return {
            "getname": {
                "token": {"url": "dy:test-table", "params": {}},
                "params": {},
            }
        }

    @pytest.fixture
    def service(self, config):
        return DynamoDBNameService(config, "test_schema")

    @patch("services.name_service.boto3")
    def test_get_single_name_success(self, mock_boto3, service):
        """Test successful single patient name retrieval from DynamoDB"""
        # Mock DynamoDB response
        mock_table = MagicMock()
        mock_table.get_item.return_value = {
            "Item": {"schema_fkpessoa": "12345", "nome": "John Doe"}
        }
        mock_boto3.resource.return_value.Table.return_value = mock_table

        result = service.get_single_name(12345)

        assert result["status"] == "success"
        assert result["idPatient"] == 12345
        assert result["name"] == "John Doe"
        mock_table.get_item.assert_called_once()

    @patch("services.name_service.boto3")
    def test_get_single_name_not_found(self, mock_boto3, service):
        """Test patient not found in DynamoDB"""
        mock_table = MagicMock()
        mock_table.get_item.return_value = {}
        mock_boto3.resource.return_value.Table.return_value = mock_table

        result = service.get_single_name(12345)

        assert result["status"] == "error"
        assert result["idPatient"] == 12345
        assert "Paciente 12345" in result["name"]

    def test_search_by_name_not_supported(self, service):
        """Test that search is not supported for DynamoDB"""
        result = service.search_by_name("John")
        assert result == []


class TestNHInternalNameService:
    """Test NoHarm internal name service strategy"""

    @pytest.fixture
    def config(self):
        return {
            "getname": {
                "internal": True,
                "url": "https://api.noharm.com/",
                "token": {"url": "internal", "params": {"client_secret": "secret123"}},
                "params": {"schema": "test_schema"},
            }
        }

    @pytest.fixture
    def service(self, config):
        return NHInternalNameService(config, "test_schema")

    @patch("services.name_service.requests.get")
    @patch("services.name_service.encode")
    def test_get_single_name_success(self, mock_encode, mock_get, service):
        """Test successful single patient name retrieval from NH Internal"""
        mock_encode.return_value = "mock_jwt_token"
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "idPatient": 12345,
            "name": "Jane Smith",
            "data": {"extra": "info"},
        }
        mock_get.return_value = mock_response

        result = service.get_single_name(12345)

        assert result["status"] == "success"
        assert result["idPatient"] == 12345
        assert result["name"] == "Jane Smith"
        assert result["data"]["extra"] == "info"

    @patch("services.name_service.requests.post")
    @patch("services.name_service.encode")
    def test_get_multiple_names_success(self, mock_encode, mock_post, service):
        """Test multiple patient names retrieval"""
        mock_encode.return_value = "mock_jwt_token"
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"idPatient": 123, "name": "Patient One"},
            {"idPatient": 456, "name": "Patient Two"},
        ]
        mock_post.return_value = mock_response

        result = service.get_multiple_names([123, 456, 789])

        assert len(result) == 3
        assert result[0]["status"] == "success"
        assert result[0]["name"] == "Patient One"
        assert result[1]["status"] == "success"
        assert result[2]["status"] == "error"  # 789 not found

    @patch("services.name_service.requests.get")
    @patch("services.name_service.encode")
    def test_search_by_name_success(self, mock_encode, mock_get, service):
        """Test search by name functionality"""
        mock_encode.return_value = "mock_jwt_token"
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {
                    "name": "John Doe",
                    "idPatient": 123,
                    "dtnascimento": "1990-01-01",
                    "cpf": "12345678900",
                },
                {
                    "name": "John Smith",
                    "idPatient": 456,
                    "dtnascimento": "1985-05-15",
                    "cpf": "98765432100",
                },
            ]
        }
        mock_get.return_value = mock_response

        result = service.search_by_name("John")

        assert len(result) == 2
        assert result[0]["name"] == "John Doe"
        assert result[0]["idPatient"] == 123


class TestExternalNameService:
    """Test external OAuth-based name service strategy"""

    @pytest.fixture
    def config(self):
        return {
            "getname": {
                "internal": False,
                "url": "https://external-api.com/patients",
                "token": {
                    "url": "https://external-api.com/oauth/token",
                    "params": {
                        "grant_type": "client_credentials",
                        "client_id": "client123",
                        "client_secret": "secret456",
                    },
                },
                "params": {},
                "authPrefix": "Bearer ",
            }
        }

    @pytest.fixture
    def service(self, config):
        return ExternalNameService(config, "test_schema")

    @patch("services.name_service.requests.post")
    @patch("services.name_service.requests.get")
    def test_get_single_name_success(self, mock_get, mock_post, service):
        """Test successful single patient name retrieval from external service"""
        # Mock token request
        mock_token_response = Mock()
        mock_token_response.status_code = 200
        mock_token_response.json.return_value = {"access_token": "oauth_token_123"}
        mock_post.return_value = mock_token_response

        # Mock patient data request
        mock_patient_response = Mock()
        mock_patient_response.status_code = 200
        mock_patient_response.json.return_value = {
            "data": [{"idPatient": 12345, "name": "External Patient"}]
        }
        mock_get.return_value = mock_patient_response

        result = service.get_single_name(12345)

        assert result["status"] == "success"
        assert result["idPatient"] == 12345
        assert result["name"] == "External Patient"

    @patch("services.name_service.requests.post")
    def test_token_error(self, mock_post, service):
        """Test token retrieval error"""
        mock_token_response = Mock()
        mock_token_response.status_code = 401
        mock_post.return_value = mock_token_response

        with pytest.raises(Exception):
            service._get_token()


class TestNameServiceFactory:
    """Test the factory pattern for creating service instances"""

    def test_create_dynamodb_service(self):
        """Test factory creates DynamoDB service"""
        config = {"getname": {"token": {"url": "dy:table-name"}}}
        service = NameServiceFactory.create_service(config, "test_schema")
        assert isinstance(service, DynamoDBNameService)

    def test_create_nh_internal_service(self):
        """Test factory creates NH Internal service"""
        config = {
            "getname": {
                "internal": True,
                "token": {"url": "internal", "params": {"client_secret": "secret"}},
            }
        }
        service = NameServiceFactory.create_service(config, "test_schema")
        assert isinstance(service, NHInternalNameService)

    def test_create_external_service(self):
        """Test factory creates External service"""
        config = {
            "getname": {
                "internal": False,
                "token": {"url": "https://oauth.example.com/token"},
            }
        }
        service = NameServiceFactory.create_service(config, "test_schema")
        assert isinstance(service, ExternalNameService)

    def test_create_external_service_default(self):
        """Test factory defaults to External service when no flags set"""
        config = {"getname": {"token": {"url": "https://api.example.com/token"}}}
        service = NameServiceFactory.create_service(config, "test_schema")
        assert isinstance(service, ExternalNameService)


class TestServiceStrategyCommon:
    """Test common functionality across all strategies"""

    @pytest.fixture
    def service(self):
        config = {"getname": {"url": "https://api.com", "urlDev": "http://localhost"}}
        return ExternalNameService(config, "test_schema")

    def test_create_error_response(self, service):
        """Test standard error response format"""
        result = service._create_error_response(12345)
        assert result["status"] == "error"
        assert result["idPatient"] == 12345
        assert "Paciente 12345" in result["name"]

    @patch("services.name_service.Config")
    def test_get_url_production(self, mock_config, service):
        """Test URL selection in production environment"""
        mock_config.ENV = "production"
        url = service._get_url()
        assert url == "https://api.com"

    @patch("services.name_service.Config")
    def test_get_url_development(self, mock_config, service):
        """Test URL selection in development environment"""
        mock_config.ENV = "development"
        url = service._get_url()
        assert url == "http://localhost"
