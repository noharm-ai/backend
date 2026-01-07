"""Route: names proxy"""

import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import requests
from flask import Blueprint, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from jwt import encode

from config import Config
from exception.validation_error import ValidationError
from models.appendix import SchemaConfig
from models.enums import NoHarmENV
from models.main import User, db, dbSession
from services import name_service
from utils import status

# TODO: refactor
app_names = Blueprint("app_names", __name__)

logging.basicConfig()
logger = logging.getLogger("noharm.getname")

TIMEOUT = 15
CHUNK_SIZE = 200


@app_names.route("/names/<int:idPatient>", methods=["GET"])
@jwt_required()
def proxy_name(idPatient):
    """Proxy get single name"""
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    config = _get_config(user)

    if config["getname"]["token"]["url"].startswith("dy"):
        # internal query
        response = name_service.get_name_from_dynamo(
            id_patient=idPatient, config=config
        )

        return response, status.HTTP_200_OK if response.get(
            "status"
        ) == "success" else status.HTTP_400_BAD_REQUEST

    token = _get_token(config)
    is_internal = config["getname"].get("internal", False)
    auth_prefix = config["getname"].get("authPrefix", "")
    url = _get_url(config=config)

    if is_internal:
        url += f"patient-name/{int(idPatient)}"
        params = dict(config["getname"]["params"])
    else:
        params = dict(config["getname"]["params"], **{"cd_paciente": idPatient})

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

            if is_internal:
                return {
                    "status": "success",
                    "idPatient": data["idPatient"],
                    "name": data["name"],
                    "data": data["data"],
                }, status.HTTP_200_OK

            if len(data["data"]) > 0:
                patient = data["data"][0]

                return {
                    "status": "success",
                    "idPatient": patient["idPatient"],
                    "name": patient["name"],
                }, status.HTTP_200_OK

        logger.warning("GETNAME: %s #%s#", response.status_code, user.schema)
        logger.warning(url)
        logger.warning(params)
        logger.warning(response.text)
        logger.warning(response.__dict__)
    except requests.exceptions.RequestException as e:
        logger.warning("GETNAME: 500 #%s#", user.schema)
        logger.warning(url)
        logger.warning(params)
        logger.warning(str(e))

    return {
        "status": "error",
        "idPatient": int(idPatient),
        "name": f"Paciente {str(int(idPatient))}",
    }, status.HTTP_400_BAD_REQUEST


@app_names.route("/names", methods=["POST"])
@jwt_required()
def proxy_multiple():
    """Proxy get multiple names"""
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    data = request.get_json()
    ids_list = data.get("patients", [])
    config = _get_config(user)
    token = _get_token(config)

    chunks = [ids_list[i : i + CHUNK_SIZE] for i in range(0, len(ids_list), CHUNK_SIZE)]
    names = []

    for chunk in chunks:
        names += _getname_multiple_iteration(
            config=config, ids_list=chunk, token=token, schema=user.schema
        )

    return names, status.HTTP_200_OK


def _getname_multiple_iteration(config: dict, ids_list: list, token: str, schema: str):
    url = _get_url(config=config)
    is_internal = config["getname"].get("internal", False)
    auth_prefix = config["getname"].get("authPrefix", "")
    names = []
    found = []

    try:
        if is_internal:
            url += "patient-name/multiple"
            params = dict(
                config["getname"]["params"],
                **{"patients": [str(id) for id in ids_list]},
            )
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
        else:
            params = dict(
                config["getname"]["params"],
                **{"cd_paciente": " ".join(str(id) for id in ids_list)},
            )
            response = requests.get(
                url,
                headers={"Authorization": f"{auth_prefix}{token}"},
                params=params,
                verify=False,
                timeout=TIMEOUT,
            )

        if response.status_code == status.HTTP_200_OK:
            data = response.json()
            results = data if is_internal else data["data"]

            for p in results:
                found.append(str(p["idPatient"]))
                names.append(
                    {
                        "status": "success",
                        "idPatient": p["idPatient"],
                        "name": p["name"],
                    }
                )
        else:
            logger.warning("GETNAME: %s #%s#", response.status_code, schema)
            logger.warning(url)
            logger.warning(params)
            logger.warning(response.text)
            logger.warning(response.__dict__)

    except requests.exceptions.RequestException as e:
        logger.warning("GETNAME: 500 #%s#", schema)
        logger.warning(url)
        logger.warning(params)
        logger.warning(str(e))

    for id_patient in ids_list:
        if str(id_patient) not in found:
            names.append(
                {
                    "status": "error",
                    "idPatient": int(id_patient),
                    "name": "Paciente " + str(int(id_patient)),
                }
            )

    return names


@app_names.route("/names/auth-token", methods=["GET"])
@jwt_required()
def auth_token():
    """get internal token"""
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    schema_config = (
        db.session.query(SchemaConfig)
        .filter(SchemaConfig.schemaName == user.schema)
        .first()
    )

    getname_config = (
        schema_config.config.get("getname", {}) if schema_config.config else {}
    )
    key = getname_config.get("secret", "")

    if not key:
        return {
            "status": "error",
            "message": "Invalid key",
        }, status.HTTP_400_BAD_REQUEST

    token = encode(
        payload={
            "exp": datetime.now(tz=timezone.utc) + timedelta(minutes=2),
            "iss": "noharm",
        },
        key=key,
    )

    return {"status": "success", "data": token}


@app_names.route("/names/search/<string:term>", methods=["GET"])
@jwt_required()
def search_name(term):
    """inverted name search"""
    max_search_results = 150
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    config = _get_config(user)
    token = _get_token(config)
    url = _get_url(config=config)

    # Sanitize and URL-encode the search term to prevent injection attacks
    sanitized_term = quote(term, safe="")
    url += f"search-name/{sanitized_term}"
    params = dict(config["getname"]["params"])

    try:
        response = requests.get(
            url, headers={"Authorization": f"Bearer {token}"}, params=params, timeout=20
        )

        if response.status_code == status.HTTP_200_OK:
            data = response.json()
            results = []
            for p in data["results"][:max_search_results]:
                results.append(
                    {
                        "name": p["name"],
                        "idPatient": p["idPatient"],
                        "birthdate": p["dtnascimento"],
                        "number": p["cpf"],
                    }
                )

            return {
                "status": "success",
                "data": sorted(results, key=lambda d: d["name"]),
            }, status.HTTP_200_OK

        if response.status_code != status.HTTP_404_NOT_FOUND:
            logger.warning("GETNAME: %s #%s#", response.status_code, user.schema)
            logger.warning(url)
            logger.warning(params)
            logger.warning(response.json())

    except requests.exceptions.RequestException as e:
        logger.warning("GETNAME: 500 #%s#", user.schema)
        logger.warning(url)
        logger.warning(params)
        logger.warning(str(e))

    return {"status": "error", "data": []}, status.HTTP_200_OK


def _get_token(config):
    token_url = config["getname"]["token"]["url"]
    params = config["getname"]["token"]["params"]
    is_internal = config["getname"].get("internal", False)

    if is_internal:
        token = encode(
            payload={
                "exp": datetime.now(tz=timezone.utc) + timedelta(minutes=2),
                "iss": "noharm",
            },
            key=params["client_secret"],
        )

        return token

    response = requests.post(url=token_url, data=params, verify=False, timeout=TIMEOUT)

    if response.status_code != status.HTTP_200_OK:
        raise ValidationError(
            "Token inválido",
            "errors.unauthorizedUser",
            response.status_code,
        )

    token_data = response.json()

    return token_data["access_token"]


def _get_config(user: User):
    schema_config = (
        db.session.query(SchemaConfig)
        .filter(SchemaConfig.schemaName == user.schema)
        .first()
    )

    if schema_config.config == None or "getname" not in schema_config.config:
        raise ValidationError(
            "Getname sem configuração",
            "errors.invalid",
            status.HTTP_400_BAD_REQUEST,
        )

    return schema_config.config


def _get_url(config: dict):
    url_dev = config["getname"].get("urlDev", None)
    url_prod = config["getname"].get("url", None)
    return (
        url_dev if Config.ENV == NoHarmENV.DEVELOPMENT.value and url_dev else url_prod
    )
