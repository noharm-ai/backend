import jwt
import json
import logging
import requests
from flask import request
from http.client import HTTPConnection
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
)
from cryptography.hazmat.primitives import serialization
from flask_sqlalchemy.session import Session
from markupsafe import escape as escape_html
from sqlalchemy import asc

from models.main import db, dbSession, Notify, User
from models.appendix import Memory, SchemaConfig
from models.segment import Hospital, Segment
from models.enums import (
    NoHarmENV,
    MemoryEnum,
    FeatureEnum,
    IntegrationStatusEnum,
    UserAuditTypeEnum,
)
from services import memory_service, user_service
from services.admin import admin_integration_status_service
from config import Config
from exception.validation_error import ValidationError
from utils import status
from security.role import Role
from security.permission import Permission


def _has_force_schema_permission(user: User):
    if user.schema != "hsc_test":
        return False

    permissions = Role.get_permissions_from_user(user=user)

    return Permission.MULTI_SCHEMA in permissions


def _auth_user(
    user,
    force_schema=None,
    extra_features=[],
):
    permissions = Role.get_permissions_from_user(user=user)
    roles = user.config["roles"] if user.config and "roles" in user.config else []
    user_features = (
        user.config["features"] if user.config and "features" in user.config else []
    )

    if Config.ENV == NoHarmENV.STAGING.value:
        if FeatureEnum.STAGING_ACCESS.value not in user_features:
            raise ValidationError(
                "Este é o ambiente de homologação da NoHarm. Acesse {} para utilizar a NoHarm.".format(
                    Config.APP_URL
                ),
                "errors.unauthorizedUser",
                status.HTTP_401_UNAUTHORIZED,
            )

    user_schema = user.schema
    user_config = user.config
    if force_schema and _has_force_schema_permission(user):
        user_schema = force_schema
        user_config = dict(
            user.config,
            **{
                "features": user_features + extra_features,
            },
        )

    schema_config = (
        db.session.query(SchemaConfig)
        .filter(SchemaConfig.schemaName == user_schema)
        .first()
    )
    if (
        FeatureEnum.DISABLE_CPOE.value in user_features
        or FeatureEnum.DISABLE_CPOE.value in extra_features
    ):
        is_cpoe = False
    else:
        is_cpoe = schema_config.cpoe

    # keep compatibility (remove after transition)
    if is_cpoe:
        user_config = dict(
            user_config,
            **{
                "roles": roles + ["cpoe"],
            },
        )

    claims = {"schema": user_schema, "config": user_config, "cpoe": is_cpoe}
    access_token = create_access_token(identity=user.id, additional_claims=claims)
    refresh_token = create_refresh_token(identity=user.id, additional_claims=claims)

    db_session = Session(db)
    db_session.connection(
        execution_options={"schema_translate_map": {None: user_schema}}
    )

    notification = Notify.getNotification(schema=user_schema)

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
    preferences = (
        db_session.query(Memory)
        .filter(Memory.kind == f"user-preferences-{user.id}")
        .first()
    )

    mem = db_session.query(Memory).filter_by(kind="getnameurl").first()
    nameUrl = mem.value if mem else {"value": "http://localhost/{idPatient}"}

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

    logout_url = None
    if features is not None and FeatureEnum.OAUTH.value in features.value:
        oauth_config = get_oauth_config(schema=user_schema)

        logout_url = oauth_config["logout_url"] if oauth_config is not None else None

    db_session.close()

    integration_status = admin_integration_status_service.get_integration_status(
        user_schema
    )
    if (
        integration_status == IntegrationStatusEnum.CANCELED.value
        and Permission.MAINTAINER not in permissions
    ):
        raise ValidationError(
            "Integração Cancelada",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    extra_audit = {
        "schema": user_schema,
        "env": Config.ENV,
        "userAgent": request.headers.get("User-Agent"),
    }
    user_service.create_audit(
        auditType=UserAuditTypeEnum.LOGIN,
        id_user=user.id,
        responsible=user,
        extra=extra_audit,
    )

    return {
        "status": "success",
        "userName": user.name,
        "userId": user.id,
        "email": user.email,
        "schema": escape_html(user_schema),
        "roles": user_config["roles"] if user_config and "roles" in user_config else [],
        "userFeatures": (
            user_config["features"] if user_config and "features" in user_config else []
        ),
        "features": features.value if features is not None else [],
        "preferences": preferences.value if preferences is not None else None,
        "nameUrl": nameUrl["value"] if "value" in nameUrl else None,
        "multipleNameUrl": nameUrl["multiple"] if "multiple" in nameUrl else None,
        "nameHeaders": nameUrl["headers"] if "headers" in nameUrl else {},
        "proxy": nameUrl["proxy"] if "proxy" in nameUrl else False,
        "notify": notification,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "apiKey": Config.API_KEY if hasattr(Config, "API_KEY") else "",
        "segments": segmentList,
        "hospitals": hospitalList,
        "logoutUrl": logout_url,
        "integrationStatus": integration_status,
        "permissions": [p.name for p in permissions],
    }


def pre_auth(email, password):
    user = User.authenticate(email, password)

    if user is None:
        raise ValidationError(
            "Usuário inválido",
            "errors.unauthorizedUser",
            status.HTTP_400_BAD_REQUEST,
        )

    if _has_force_schema_permission(user):
        schema_results = db.session.query(SchemaConfig).order_by(
            SchemaConfig.schemaName
        )

        schemas = []
        for s in schema_results:
            schemas.append(
                {
                    "name": s.schemaName,
                    "defaultRoles": (
                        s.config["defaultRoles"]
                        if s.config != None and "defaultRoles" in s.config
                        else []
                    ),
                    "extraRoles": (
                        s.config["extraRoles"]
                        if s.config != None and "extraRoles" in s.config
                        else []
                    ),
                }
            )

        return {"maintainer": True, "schemas": schemas}

    return {"maintainer": False, "schemas": []}


def auth_local(
    email,
    password,
    force_schema=None,
    extra_features=[],
):
    preCheckUser = User.query.filter_by(email=email.lower()).first()

    if preCheckUser is None:
        raise ValidationError(
            "Usuário inválido",
            "errors.unauthorizedUser",
            status.HTTP_400_BAD_REQUEST,
        )

    # need to create a new session to set schema
    db_session = Session(db)
    db_session.connection(
        execution_options={"schema_translate_map": {None: preCheckUser.schema}}
    )

    features = (
        db_session.query(Memory)
        .filter(Memory.kind == MemoryEnum.FEATURES.value)
        .first()
    )

    db_session.close()

    if features is not None and FeatureEnum.OAUTH.value in features.value:
        raise ValidationError(
            "Utilize o endereço {}/login/{} para fazer login na NoHarm".format(
                Config.APP_URL, preCheckUser.schema
            ),
            "{}/login/{}".format(Config.APP_URL, preCheckUser.schema),
            status.HTTP_401_UNAUTHORIZED,
        )

    user = User.authenticate(email, password)

    if user is None:
        raise ValidationError(
            "Usuário inválido",
            "errors.unauthorizedUser",
            status.HTTP_400_BAD_REQUEST,
        )

    return _auth_user(
        user,
        force_schema=force_schema,
        extra_features=extra_features,
    )


def auth_provider(code, schema):
    if schema is None:
        raise ValidationError(
            "schema invalido",
            "errors.unauthorizedUser",
            status.HTTP_400_BAD_REQUEST,
        )

    # this one works because it's the first db interaction
    dbSession.setSchema(schema)

    if (
        Config.ENV == NoHarmENV.DEVELOPMENT.value
        or Config.ENV == NoHarmENV.STAGING.value
    ):
        HTTPConnection.debuglevel = 1
        requests_log = logging.getLogger("requests.packages.urllib3")
        requests_log.setLevel(logging.DEBUG)
        requests_log.propagate = True

    oauth_config = get_oauth_config(schema=schema)

    if oauth_config is None:
        raise ValidationError(
            "OAUTH não configurado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    if "flow" in oauth_config and oauth_config["flow"] == "authentication_basic":
        params = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": oauth_config["client_id"],
            "redirect_uri": oauth_config["redirect_uri"],
        }

        response = requests.post(
            url=oauth_config["login_url"],
            data=params,
            auth=(oauth_config["client_id"], oauth_config["client_secret"]),
        )

        if response.status_code != status.HTTP_200_OK:
            raise ValidationError(
                "OAUTH provider error",
                "errors.unauthorizedUser",
                status.HTTP_401_UNAUTHORIZED,
            )

        token_data = response.json()
        code = token_data["id_token"]

    if oauth_config["verify_signature"]:
        oauth_keys = memory_service.get_memory(MemoryEnum.OAUTH_KEYS.value)

        if oauth_keys is None:
            raise ValidationError(
                "OAUTH KEYS não configurado",
                "errors.unauthorizedUser",
                status.HTTP_401_UNAUTHORIZED,
            )
        keys = oauth_keys.value["keys"]

        token_headers = jwt.get_unverified_header(code)
        token_alg = token_headers["alg"]
        token_kid = token_headers["kid"]
        public_key = None
        for key in keys:
            if key["kid"] == token_kid:
                public_key = key

        rsa_pem_key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(public_key))
        rsa_pem_key_bytes = rsa_pem_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )

        try:
            jwt_user = jwt.decode(
                code,
                key=rsa_pem_key_bytes,
                algorithms=[token_alg],
                audience=[oauth_config["client_id"]],
            )
        except Exception as error:
            raise ValidationError(
                "OAUTH provider error: decode error",
                "errors.unauthorizedUser",
                status.HTTP_401_UNAUTHORIZED,
            )
    else:
        try:
            jwt_user = jwt.decode(
                code,
                options={"verify_signature": False},
            )
        except Exception as error:
            raise ValidationError(
                "OAUTH provider error: decode error",
                "errors.unauthorizedUser",
                status.HTTP_401_UNAUTHORIZED,
            )

    email_attr = oauth_config["email_attr"]
    name_attr = oauth_config["name_attr"]

    if email_attr not in jwt_user or jwt_user[email_attr] is None:
        raise ValidationError(
            "OAUTH: email inválido",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    nh_user = _get_oauth_user(
        jwt_user[email_attr],
        jwt_user[name_attr] if name_attr in jwt_user else "Usuário",
        schema,
        oauth_config,
    )

    features = (
        db.session.query(Memory)
        .filter(Memory.kind == MemoryEnum.FEATURES.value)
        .first()
    )

    if features is None or FeatureEnum.OAUTH.value not in features.value:
        raise ValidationError(
            "OAUTH bloqueado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    return _auth_user(nh_user)


def _get_oauth_user(email, name, schema, oauth_config):
    db_user = User.query.filter_by(email=email.lower()).first()

    if db_user is None:
        raise ValidationError(
            "OAUTH: o usuário deve ser cadastrado previamente na NoHarm",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    return db_user


def get_oauth_config(schema: str):
    schema_config = (
        db.session.query(SchemaConfig).filter(SchemaConfig.schemaName == schema).first()
    )

    if schema_config.config != None:
        return schema_config.config["oauth"]

    return None


def refresh_token(current_user, current_claims):
    if "schema" in current_claims:
        claims = {
            "schema": current_claims["schema"],
            "config": current_claims["config"],
        }
    else:
        raise ValidationError(
            "Request inválido",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    user = db.session.query(User).filter(User.id == current_user).first()
    if user == None:
        raise ValidationError(
            "Usuário inválido",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    if user.active == False:
        raise ValidationError(
            "Usuário inativo",
            "errors.businessRules",
            status.HTTP_401_UNAUTHORIZED,
        )

    integration_status = admin_integration_status_service.get_integration_status(
        current_claims["schema"]
    )

    permissions = Role.get_permissions_from_user(user=user)

    if (
        integration_status == IntegrationStatusEnum.CANCELED.value
        and Permission.MAINTAINER not in permissions
    ):
        raise ValidationError(
            "Usuário inválido",
            "errors.businessRules",
            status.HTTP_401_UNAUTHORIZED,
        )

    access_token = create_access_token(identity=current_user, additional_claims=claims)

    return {"access_token": access_token}
