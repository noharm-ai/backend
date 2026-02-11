"""Service: name related operations with Strategy pattern for different service types"""

from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone

import boto3
import requests
from jwt import encode

from config import Config
from exception.validation_error import ValidationError
from models.appendix import SchemaConfig
from models.enums import NoHarmENV
from models.main import User, db
from utils import logger, status

TIMEOUT = 15
CHUNK_SIZE = 200
MAX_SEARCH_RESULTS = 150


class NameServiceStrategy(ABC):
    """Abstract base class for name service strategies"""

    def __init__(self, config: dict, schema: str):
        self.config = config
        self.schema = schema

    @abstractmethod
    def get_single_name(self, id_patient: int) -> dict:
        """Get single patient name"""
        pass

    @abstractmethod
    def get_multiple_names(self, ids_list: list) -> list:
        """Get multiple patient names"""
        pass

    @abstractmethod
    def search_by_name(self, search_term: str) -> list:
        """Search patients by name"""
        pass

    def _get_url(self) -> str:
        """Get appropriate URL based on environment"""
        url_dev = self.config["getname"].get("urlDev", None)
        url_prod = self.config["getname"].get("url", None)
        return (
            url_dev
            if Config.ENV == NoHarmENV.DEVELOPMENT.value and url_dev
            else url_prod
        )

    def _create_error_response(self, id_patient: int) -> dict:
        """Create standard error response"""
        return {
            "status": "error",
            "idPatient": int(id_patient),
            "name": f"Paciente {str(int(id_patient))}",
        }


class DynamoDBNameService(NameServiceStrategy):
    """DynamoDB-based name service"""

    def get_single_name(self, id_patient: int) -> dict:
        try:
            dynamodb = boto3.resource("dynamodb", region_name="sa-east-1")
            table_name = self.config["getname"]["token"]["url"].split(":")[1]
            table = dynamodb.Table(table_name)  # type: ignore

            response = table.get_item(
                Key={
                    "schema_fkpessoa": str(id_patient),
                }
            )

            item = response.get("Item")

            if item:
                return {
                    "status": "success",
                    "idPatient": int(id_patient),
                    "name": item["nome"],
                    "data": None,
                }

            return self._create_error_response(id_patient)

        except Exception as e:
            logger.backend_logger.error(
                f"DynamoDB error for patient {id_patient} in schema {self.schema}: {str(e)}",
                exc_info=True,
            )
            return self._create_error_response(id_patient)

    def get_multiple_names(self, ids_list: list) -> list:
        """Get multiple names from DynamoDB (individual queries)"""
        names = []
        for id_patient in ids_list:
            names.append(self.get_single_name(id_patient))
        return names

    def search_by_name(self, search_term: str) -> list:
        """Search not supported for DynamoDB"""
        logger.backend_logger.warning(
            f"Search not supported for DynamoDB service in schema {self.schema}"
        )
        return []


class NHInternalNameService(NameServiceStrategy):
    """NoHarm internal name service (with JWT token)"""

    def _get_token(self) -> str:
        """Generate internal JWT token"""
        params = self.config["getname"]["token"]["params"]
        token = encode(
            payload={
                "exp": datetime.now(tz=timezone.utc) + timedelta(minutes=2),
                "iss": "noharm",
            },
            key=params["client_secret"],
        )
        return token

    def get_single_name(self, id_patient: int) -> dict:
        url = self._get_url()
        url += f"patient-name/{int(id_patient)}"
        params = dict(self.config["getname"]["params"])
        token = self._get_token()

        try:
            response = requests.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                params=params,
                verify=False,
                timeout=TIMEOUT,
            )

            if response.status_code == status.HTTP_200_OK:
                data = response.json()
                return {
                    "status": "success",
                    "idPatient": data["idPatient"],
                    "name": data["name"],
                    "data": data.get("data"),
                }

            logger.backend_logger.warning(
                f"NH Internal service error: {response.status_code} for schema {self.schema}"
            )
            logger.backend_logger.warning(f"URL: {url}, Params: {params}")

        except requests.exceptions.RequestException as e:
            logger.backend_logger.warning(
                f"NH Internal service request error for schema {self.schema}: {str(e)}"
            )

        return self._create_error_response(id_patient)

    def get_multiple_names(self, ids_list: list) -> list:
        url = self._get_url()
        url += "patient-name/multiple"
        token = self._get_token()
        params = dict(
            self.config["getname"]["params"],
            **{"patients": [str(id) for id in ids_list]},
        )

        names = []
        found = []

        try:
            response = requests.post(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=params,
                verify=False,
                timeout=TIMEOUT,
            )

            if response.status_code == status.HTTP_200_OK:
                data = response.json()
                for p in data:
                    found.append(str(p["idPatient"]))
                    names.append(
                        {
                            "status": "success",
                            "idPatient": p["idPatient"],
                            "name": p["name"],
                        }
                    )
            else:
                logger.backend_logger.warning(
                    f"NH Internal multiple service error: {response.status_code} for schema {self.schema}"
                )

        except requests.exceptions.RequestException as e:
            logger.backend_logger.warning(
                f"NH Internal multiple service request error for schema {self.schema}: {str(e)}"
            )

        # Add error responses for not found patients
        for id_patient in ids_list:
            if str(id_patient) not in found:
                names.append(self._create_error_response(id_patient))

        return names

    def search_by_name(self, search_term: str) -> list:
        url = self._get_url()
        url += f"search-name/{search_term}"
        params = dict(self.config["getname"]["params"])
        token = self._get_token()

        try:
            response = requests.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                params=params,
                timeout=20,
            )

            if response.status_code == status.HTTP_200_OK:
                data = response.json()
                results = []
                for p in data["results"][:MAX_SEARCH_RESULTS]:
                    results.append(
                        {
                            "name": p["name"],
                            "idPatient": p["idPatient"],
                            "birthdate": p["dtnascimento"],
                            "number": p["cpf"],
                        }
                    )
                return sorted(results, key=lambda d: d["name"])

            if response.status_code != status.HTTP_404_NOT_FOUND:
                logger.backend_logger.warning(
                    f"NH Internal search error: {response.status_code} for schema {self.schema}"
                )

        except requests.exceptions.RequestException as e:
            logger.backend_logger.warning(
                f"NH Internal search request error for schema {self.schema}: {str(e)}"
            )

        return []


class ExternalNameService(NameServiceStrategy):
    """External name service (with OAuth token)"""

    def _get_token(self) -> str:
        """Get OAuth token from external service"""
        token_url = self.config["getname"]["token"]["url"]
        params = self.config["getname"]["token"]["params"]

        response = requests.post(
            url=token_url, data=params, verify=False, timeout=TIMEOUT
        )

        if response.status_code != status.HTTP_200_OK:
            raise ValidationError(
                "Token inválido",
                "errors.unauthorizedUser",
                response.status_code,
            )

        token_data = response.json()
        return token_data["access_token"]

    def get_single_name(self, id_patient: int) -> dict:
        url = self._get_url()
        auth_prefix = self.config["getname"].get("authPrefix", "")
        params = dict(self.config["getname"]["params"], **{"cd_paciente": id_patient})
        token = self._get_token()

        try:
            response = requests.get(
                url,
                headers={"Authorization": f"{auth_prefix}{token}"},
                params=params,
                verify=False,
                timeout=TIMEOUT,
            )

            if response.status_code == status.HTTP_200_OK:
                data = response.json()
                if len(data["data"]) > 0:
                    patient = data["data"][0]
                    return {
                        "status": "success",
                        "idPatient": patient["idPatient"],
                        "name": patient["name"],
                    }

            logger.backend_logger.warning(
                f"External service error: {response.status_code} for schema {self.schema}"
            )
            logger.backend_logger.warning(f"URL: {url}, Params: {params}")

        except requests.exceptions.RequestException as e:
            logger.backend_logger.warning(
                f"External service request error for schema {self.schema}: {str(e)}"
            )

        return self._create_error_response(id_patient)

    def get_multiple_names(self, ids_list: list) -> list:
        url = self._get_url()
        auth_prefix = self.config["getname"].get("authPrefix", "")
        token = self._get_token()
        params = dict(
            self.config["getname"]["params"],
            **{"cd_paciente": " ".join(str(id) for id in ids_list)},
        )

        names = []
        found = []

        try:
            response = requests.get(
                url,
                headers={"Authorization": f"{auth_prefix}{token}"},
                params=params,
                verify=False,
                timeout=TIMEOUT,
            )

            if response.status_code == status.HTTP_200_OK:
                data = response.json()
                for p in data["data"]:
                    found.append(str(p["idPatient"]))
                    names.append(
                        {
                            "status": "success",
                            "idPatient": p["idPatient"],
                            "name": p["name"],
                        }
                    )
            else:
                logger.backend_logger.warning(
                    f"External multiple service error: {response.status_code} for schema {self.schema}"
                )

        except requests.exceptions.RequestException as e:
            logger.backend_logger.warning(
                f"External multiple service request error for schema {self.schema}: {str(e)}"
            )

        # Add error responses for not found patients
        for id_patient in ids_list:
            if str(id_patient) not in found:
                names.append(self._create_error_response(id_patient))

        return names

    def search_by_name(self, search_term: str) -> list:
        """Search not typically supported for external services"""
        logger.backend_logger.warning(
            f"Search not supported for external service in schema {self.schema}"
        )
        return []


class NameServiceFactory:
    """Factory to create appropriate name service strategy"""

    @staticmethod
    def create_service(config: dict, schema: str) -> NameServiceStrategy:
        """Create appropriate service based on config"""

        # Determine service type
        token_url = config["getname"]["token"]["url"]
        is_internal = config["getname"].get("internal", False)

        if token_url.startswith("dy"):
            return DynamoDBNameService(config, schema)
        elif is_internal:
            return NHInternalNameService(config, schema)
        else:
            return ExternalNameService(config, schema)


# Public API functions


def _get_config(user: User) -> dict:
    """Get name service configuration for user's schema"""
    schema_config = (
        db.session.query(SchemaConfig)
        .filter(SchemaConfig.schemaName == user.schema)
        .first()
    )

    if (
        not schema_config
        or schema_config.config is None
        or "getname" not in schema_config.config
    ):
        raise ValidationError(
            "Getname sem configuração",
            "errors.invalid",
            status.HTTP_400_BAD_REQUEST,
        )

    return schema_config.config


def get_patient_name(id_patient: int, user: User) -> dict:
    """Get single patient name using appropriate service"""
    config = _get_config(user)
    service = NameServiceFactory.create_service(config, user.schema)
    return service.get_single_name(id_patient)


def get_multiple_patient_names(ids_list: list, user: User) -> list:
    """Get multiple patient names using appropriate service"""
    config = _get_config(user)
    service = NameServiceFactory.create_service(config, user.schema)

    # Process in chunks
    chunks = [ids_list[i : i + CHUNK_SIZE] for i in range(0, len(ids_list), CHUNK_SIZE)]
    names = []

    for chunk in chunks:
        names += service.get_multiple_names(chunk)

    return names


def search_patient_by_name(search_term: str, user: User) -> list:
    """Search patients by name using appropriate service"""
    config = _get_config(user)
    service = NameServiceFactory.create_service(config, user.schema)
    return service.search_by_name(search_term)


def generate_internal_token(user: User) -> str:
    """Generate internal JWT token for authentication"""
    schema_config = (
        db.session.query(SchemaConfig)
        .filter(SchemaConfig.schemaName == user.schema)
        .first()
    )

    if not schema_config or not schema_config.config:
        raise ValidationError(
            "Invalid configuration",
            "errors.unauthorizedUser",
            status.HTTP_400_BAD_REQUEST,
        )

    getname_config = schema_config.config.get("getname", {})
    key = getname_config.get("secret", "")

    if not key:
        raise ValidationError(
            "Invalid key",
            "errors.unauthorizedUser",
            status.HTTP_400_BAD_REQUEST,
        )

    token = encode(
        payload={
            "exp": datetime.now(tz=timezone.utc) + timedelta(minutes=2),
            "iss": "noharm",
        },
        key=key,
    )

    return token
