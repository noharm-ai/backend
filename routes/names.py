import requests
import logging
from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from jwt import encode
from datetime import datetime, timedelta, timezone

from models.main import User, dbSession, db
from models.appendix import SchemaConfig
from models.enums import NoHarmENV
from exception.validation_error import ValidationError
from config import Config
from utils import status

# TODO: refactor
app_names = Blueprint("app_names", __name__)


@app_names.route("/names/<int:idPatient>", methods=["GET"])
@jwt_required()
def proxy_name(idPatient):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    config = _get_config(user)
    token = _get_token(config)
    client_id = config["getname"]["token"]["params"]["client_id"]

    url = (
        config["getname"]["urlDev"]
        if Config.ENV == NoHarmENV.DEVELOPMENT.value
        else config["getname"]["url"]
    )

    if client_id == "noharm-internal":
        url += f"patient-name/{int(idPatient)}"
        params = dict(config["getname"]["params"])
    else:
        params = dict(config["getname"]["params"], **{"cd_paciente": idPatient})

    try:
        response = requests.get(
            url,
            headers={
                "Authorization": (
                    f"Bearer {token}" if client_id == "noharm-internal" else token
                )
            },
            params=params,
        )

        if response.status_code == status.HTTP_200_OK:
            data = response.json()

            if client_id == "noharm-internal":
                return {
                    "status": "success",
                    "idPatient": data["idPatient"],
                    "name": data["name"],
                    "data": data["data"],
                }, status.HTTP_200_OK

            else:
                if len(data["data"]) > 0:
                    patient = data["data"][0]

                    return {
                        "status": "success",
                        "idPatient": patient["idPatient"],
                        "name": patient["name"],
                    }, status.HTTP_200_OK

        logging.basicConfig()
        logger = logging.getLogger("noharm.backend")
        logger.error(f"Service names ERROR: {response.status_code}")
        logger.error(url)
        logger.error(params)
        logger.error(response.json())
    except Exception as e:
        logging.basicConfig()
        logger = logging.getLogger("noharm.backend")
        logger.error("Service names ERROR (exception)")
        logger.error(url)
        logger.error(params)
        logger.exception(e)

    return {
        "status": "error",
        "idPatient": int(idPatient),
        "name": f"Paciente {str(int(idPatient))}",
    }, status.HTTP_400_BAD_REQUEST


@app_names.route("/names", methods=["POST"])
@jwt_required()
def proxy_multiple():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    data = request.get_json()
    ids_list = data.get("patients", [])
    config = _get_config(user)
    token = _get_token(config)
    client_id = config["getname"]["token"]["params"]["client_id"]

    url = (
        config["getname"]["urlDev"]
        if Config.ENV == NoHarmENV.DEVELOPMENT.value
        else config["getname"]["url"]
    )

    try:
        if client_id == "noharm-internal":
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
            )
        else:
            params = dict(
                config["getname"]["params"],
                **{"cd_paciente": " ".join(str(id) for id in ids_list)},
            )
            response = requests.get(
                url, headers={"Authorization": token}, params=params
            )

        found = []
        names = []
        if response.status_code == status.HTTP_200_OK:
            data = response.json()
            results = data if client_id == "noharm-internal" else data["data"]

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
            logging.basicConfig()
            logger = logging.getLogger("noharm.backend")
            logger.error(f"Service names error {response.status_code}")
            logger.error(response.json())
            logger.error(url)
            logger.error(params)

    except Exception as e:
        logging.basicConfig()
        logger = logging.getLogger("noharm.backend")
        logger.error(f"Service names ERROR (exception)")
        logger.error(url)
        logger.error(params)
        logger.exception(e)

    for id_patient in ids_list:
        if str(id_patient) not in found:
            names.append(
                {
                    "status": "error",
                    "idPatient": int(id_patient),
                    "name": "Paciente " + str(int(id_patient)),
                }
            )

    return names, status.HTTP_200_OK


@app_names.route("/names/auth-token", methods=["GET"])
@jwt_required()
def auth_token():
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
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    config = _get_config(user)
    token = _get_token(config)

    url = (
        config["getname"]["urlDev"]
        if Config.ENV == NoHarmENV.DEVELOPMENT.value
        else config["getname"]["url"]
    )

    url += f"search-name/{term}"
    params = dict(config["getname"]["params"])

    try:
        response = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            params=params,
        )

        if response.status_code == status.HTTP_200_OK:
            data = response.json()
            results = []
            for p in data["results"]:
                results.append({"name": p["name"], "idPatient": p["idPatient"]})

            return {
                "status": "success",
                "data": sorted(results, key=lambda d: d["name"]),
            }, status.HTTP_200_OK

        logging.basicConfig()
        logger = logging.getLogger("noharm.backend")
        logger.error(f"Service names ERROR: {response.status_code}")
        logger.error(url)
        logger.error(params)
        logger.error(response.json())
    except Exception as e:
        logging.basicConfig()
        logger = logging.getLogger("noharm.backend")
        logger.error("Service names ERROR (exception)")
        logger.error(url)
        logger.error(params)
        logger.exception(e)

    return {"status": "error", "data": []}, status.HTTP_400_BAD_REQUEST


def _get_token(config):
    token_url = config["getname"]["token"]["url"]
    params = config["getname"]["token"]["params"]

    if params["client_id"] == "noharm-internal":
        token = encode(
            payload={
                "exp": datetime.now(tz=timezone.utc) + timedelta(minutes=2),
                "iss": "noharm",
            },
            key=params["client_secret"],
        )

        return token

    response = requests.post(url=token_url, data=params)

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
