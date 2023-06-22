import jwt
import logging
import requests
from http.client import HTTPConnection
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
)

from models.main import *
from models.appendix import *
from models.prescription import *
from models.enums import NoHarmENV, MemoryEnum, FeatureEnum
from services import memory_service
from config import Config
from exception.validation_error import ValidationError


def _auth_user(user, db_session):
    if Config.ENV == NoHarmENV.STAGING.value:
        roles = user.config["roles"] if user.config and "roles" in user.config else []
        if "suporte" not in roles and "admin" not in roles and "staging" not in roles:
            raise ValidationError(
                "Este é o ambiente de homologação da NoHarm. Acesse {} para utilizar a NoHarm.".format(
                    Config.APP_URL
                ),
                "errors.unauthorizedUser",
                status.HTTP_401_UNAUTHORIZED,
            )

    claims = {"schema": user.schema, "config": user.config}
    access_token = create_access_token(identity=user.id, additional_claims=claims)
    refresh_token = create_refresh_token(identity=user.id, additional_claims=claims)

    notification = Notify.getNotification(schema=user.schema)

    if notification is not None:
        notificationMemory = (
            db_session.query(Memory)
            .filter(
                Memory.kind
                == "info-alert-" + str(notification["id"]) + "-" + str(user.id)
            )
            .first()
        )

        if notificationMemory is not None:
            notification = None

    features = db_session.query(Memory).filter(Memory.kind == "features").first()

    nameUrl = Memory.getNameUrl(user.schema)

    hospitals = db_session.query(Hospital).order_by(asc(Hospital.name)).all()
    hospitalList = []
    for h in hospitals:
        hospitalList.append({"id": h.id, "name": h.name})

    segments = db_session.query(Segment).order_by(asc(Segment.description)).all()
    segmentList = []
    for s in segments:
        segmentList.append(
            {"id": s.id, "description": s.description, "status": s.status}
        )

    return {
        "status": "success",
        "userName": user.name,
        "userId": user.id,
        "email": user.email,
        "schema": user.schema,
        "roles": user.config["roles"] if user.config and "roles" in user.config else [],
        "userFeatures": user.config["features"]
        if user.config and "features" in user.config
        else [],
        "features": features.value if features is not None else [],
        "nameUrl": nameUrl["value"]
        if user.permission()
        else "http://localhost/{idPatient}",
        "multipleNameUrl": nameUrl["multiple"]
        if "multiple" in nameUrl and user.permission()
        else None,
        "nameHeaders": nameUrl["headers"] if "headers" in nameUrl else {},
        "proxy": True if "to" in nameUrl else False,
        "notify": notification,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "apiKey": Config.API_KEY if hasattr(Config, "API_KEY") else "",
        "segments": segmentList,
        "hospitals": hospitalList,
    }


def auth_local(email, password):
    user = User.authenticate(email, password)

    if user is None:
        raise ValidationError(
            "Usuário inválido",
            "errors.unauthorizedUser",
            status.HTTP_400_BAD_REQUEST,
        )

    # need to create a new session to set schema
    db_session = db.create_scoped_session()
    db_session.connection(
        execution_options={"schema_translate_map": {None: user.schema}}
    )

    features = (
        db_session.query(Memory)
        .filter(Memory.kind == MemoryEnum.FEATURES.value)
        .first()
    )

    if features is not None and FeatureEnum.OAUTH.value in features.value:
        raise ValidationError(
            "Utilize o endereço {}/{} para fazer login na NoHarm".format(
                Config.APP_URL, user.schema
            ),
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    return _auth_user(user, db_session)


def auth_provider(code, schema):
    if schema is None:
        raise ValidationError(
            "schema invalido",
            "errors.unauthorizedUser",
            status.HTTP_400_BAD_REQUEST,
        )

    # this one works because it's the first db interaction
    dbSession.setSchema(schema)

    if Config.ENV == NoHarmENV.STAGING.value:
        HTTPConnection.debuglevel = 1
        requests_log = logging.getLogger("requests.packages.urllib3")
        requests_log.setLevel(logging.DEBUG)
        requests_log.propagate = True

    oauth_config = memory_service.get_memory(MemoryEnum.OAUTH_CONFIG.value)

    if oauth_config is None:
        raise ValidationError(
            "OAUTH não configurado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    features = (
        db.session.query(Memory)
        .filter(Memory.kind == MemoryEnum.FEATURES.value)
        .first()
    )

    if features is not None and FeatureEnum.OAUTH.value not in features.value:
        raise ValidationError(
            "OAUTH bloqueado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    params = {"grant_type": "authorization_code", "code": code}

    response = requests.post(url=oauth_config.value["login_url"], data=params)

    if response.status_code != status.HTTP_200_OK:
        raise ValidationError(
            "OAUTH provider error",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    auth_data = response.json()
    jwt_user = jwt.decode(auth_data["id_token"], options={"verify_signature": False})

    if "email" not in jwt_user or jwt_user["email"] is None:
        raise ValidationError(
            "OAUTH: email inválido",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    nh_user = _get_oauth_user(jwt_user, schema)

    return _auth_user(nh_user, db.session)


def _get_oauth_user(user, schema):
    db_user = User.query.filter_by(email=user["email"]).first()

    if db_user is None:
        nh_user = User()
        nh_user.name = user["name"] if "name" in user else "Usuário"
        nh_user.email = user["email"]
        nh_user.password = "#"
        nh_user.schema = schema
        nh_user.config = {
            "roles": ["staging"] if Config.ENV == NoHarmENV.STAGING.value else []
        }
        nh_user.active = True

        db.session.add(nh_user)

        return nh_user

    return db_user
