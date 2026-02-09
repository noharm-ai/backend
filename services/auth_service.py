"""Service for handling authentication and authorization in the NoHarm application."""

import json
import urllib.parse

import jwt
import requests
from cryptography.hazmat.primitives import serialization
from flask import request
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
)
from flask_sqlalchemy.session import Session
from markupsafe import escape as escape_html
from sqlalchemy import asc, text
from sqlalchemy.orm import make_transient

from config import Config
from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from models.appendix import Memory, SchemaConfig
from models.enums import (
    FeatureEnum,
    IntegrationStatusEnum,
    MemoryEnum,
    NoHarmENV,
    UserAuditTypeEnum,
)
from models.main import Notify, User, UserExtra, db, dbSession
from models.segment import Hospital, Segment
from repository import user_repository
from security.role import Role
from services import memory_service, user_service
from services.admin import admin_integration_status_service
from utils import status


def _login(email: str, password: str) -> User:
    user = user_repository.get_user_by_credentials(email=email, password=password)

    if not user:
        raise ValidationError(
            "Usuário inválido",
            "errors.unauthorizedUser",
            status.HTTP_400_BAD_REQUEST,
        )

    return _prepare_user(user=user)


def _prepare_user(user: User) -> User:
    """add extra info to user config"""

    # detach from session
    make_transient(user)

    # TODO: add special roles test
    # special_roles = Role.get_special_roles()
    special_roles = []
    if (
        len(set.intersection(set(user.config.get("roles", [])), set(special_roles))) > 0
        or len(user.config.get("schemas", [])) > 0
    ):
        raise ValidationError(
            "Configuração de usuário corrompida/inválida",
            "errors.unauthorizedUser",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    extra = db.session.query(UserExtra).filter(UserExtra.idUser == user.id).first()
    if extra:
        extra_roles = extra.config.get("roles", [])
        extra_schemas = extra.config.get("schemas", [])
        user.config = dict(
            user.config,
            **{
                "roles": user.config.get("roles", []) + extra_roles,
                "schemas": user.config.get("schemas", []) + extra_schemas,
            },
        )

    return user


def _has_force_schema_permission(user: User, force_schema: str = None):
    permissions = Role.get_permissions_from_user(user=user)

    if Permission.MULTI_SCHEMA not in permissions:
        return False

    if Permission.MAINTAINER not in permissions and force_schema is not None:
        valid_schemas = [schema["name"] for schema in user.config.get("schemas", [])]
        return force_schema in valid_schemas

    return True


def _auth_user(
    user,
    force_schema=None,
    extra_features=None,
):
    """Authenticate user and return user data with access and refresh tokens."""

    permissions = Role.get_permissions_from_user(user=user)
    roles = user.config["roles"] if user.config and "roles" in user.config else []
    user_features = (
        user.config["features"] if user.config and "features" in user.config else []
    )
    extra_features = [] if extra_features is None else extra_features

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
    if force_schema and not _has_force_schema_permission(
        user=user, force_schema=force_schema
    ):
        raise ValidationError(
            "Usuário não autorizado neste recurso",
            "errors.invalidParams",
            status.HTTP_401_UNAUTHORIZED,
        )

    if force_schema and _has_force_schema_permission(
        user=user, force_schema=force_schema
    ):
        if Role.NAVIGATOR.value in roles and user_schema != force_schema:
            # if NAVIGATOR in a external schema, add fixed roles
            user_config = dict(
                user.config,
                **{
                    "roles": [Role.NAVIGATOR.value, Role.VIEWER.value],
                },
            )

        user_schema = force_schema
        if Permission.MAINTAINER in permissions:
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

    claims = {"schema": user_schema, "config": user_config}
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
            {
                "id": s.id,
                "description": s.description,
                "status": s.status,
                "type": s.type,
                "cpoe": s.cpoe,
            }
        )

    logout_url = None
    is_oauth = False
    if features is not None and FeatureEnum.OAUTH.value in features.value:
        is_oauth = True
        logout_url = Config.MAIL_HOST + "/login/" + user_schema

    if permissions is not None and Permission.MAINTAINER in permissions:
        is_oauth = True
        logout_url = Config.MAIL_HOST + "/login/noharm"

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

    if Config.ENV != NoHarmENV.DEVELOPMENT.value:
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

    getname_config = (
        schema_config.config.get("getname", {}) if schema_config.config else {}
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
        "getnameType": getname_config.get("type", "default"),
        "proxy": (
            nameUrl["proxy"] if "proxy" in nameUrl else False
        ),  # deprecated (use getnameType)
        "notify": notification,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "apiKey": Config.API_KEY if hasattr(Config, "API_KEY") else "",
        "segments": segmentList,
        "hospitals": hospitalList,
        "logoutUrl": logout_url,
        "integrationStatus": integration_status,
        "permissions": [p.name for p in permissions],
        "oauth": is_oauth,
    }


# deprecated
def pre_auth(email, password):
    user = _login(email, password)

    if _has_force_schema_permission(user=user, force_schema=None):
        permissions = Role.get_permissions_from_user(user=user)

        if Permission.MAINTAINER in permissions:
            schema_results = db.session.query(SchemaConfig).order_by(
                SchemaConfig.schemaName
            )

            schemas = []
            for s in schema_results:
                schemas.append(
                    {
                        "name": s.schemaName,
                    }
                )

            return {"maintainer": True, "schemas": schemas}
        else:
            return {"maintainer": False, "schemas": user.config.get("schemas", [])}

    return {"maintainer": False, "schemas": []}


@has_permission(Permission.MULTI_SCHEMA)
def get_switch_schema_data(user_permissions: list[Permission], user_context: User):
    """Get list of schemas to choose from"""

    if Permission.MAINTAINER in user_permissions:
        schema_results = db.session.query(SchemaConfig).order_by(
            SchemaConfig.schemaName
        )

        schemas = []
        for s in schema_results:
            schemas.append(
                {
                    "name": s.schemaName,
                }
            )

        return {"maintainer": True, "schemas": schemas}

    extra = (
        db.session.query(UserExtra).filter(UserExtra.idUser == user_context.id).first()
    )
    schemas = []
    if extra:
        schemas = extra.config.get("schemas", [])

    return {"maintainer": False, "schemas": schemas}


@has_permission(Permission.MULTI_SCHEMA)
def switch_schema(switch_to_schema: str, extra_features: list[str], user_context: User):
    """Switch to other schema"""
    user = db.session.query(User).filter(User.id == user_context.id).first()

    user = _prepare_user(user=user)

    return _auth_user(
        user=user, force_schema=switch_to_schema, extra_features=extra_features
    )


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
                Config.MAIL_HOST, preCheckUser.schema
            ),
            "{}/login/{}".format(Config.APP_URL, preCheckUser.schema),
            status.HTTP_401_UNAUTHORIZED,
        )

    user = _login(email, password)

    permissions = Role.get_permissions_from_user(user=user)

    if Permission.MAINTAINER in permissions:
        raise ValidationError(
            f"Utilize o endereço {Config.MAIL_HOST}/login/noharm para fazer login na NoHarm",
            f"{Config.MAIL_HOST}/login/noharm",
            status.HTTP_401_UNAUTHORIZED,
        )

    return _auth_user(
        user,
        force_schema=force_schema,
        extra_features=extra_features,
    )


def auth_provider(code, schema):
    """Authenticate user using OAUTH provider."""

    if schema is None:
        raise ValidationError(
            "schema invalido",
            "errors.unauthorizedUser",
            status.HTTP_400_BAD_REQUEST,
        )

    # this one works because it's the first db interaction
    _set_schema(schema)

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
            timeout=10,
        )

        if response.status_code != status.HTTP_200_OK:
            raise ValidationError(
                "OAUTH provider error",
                "errors.unauthorizedUser",
                status.HTTP_401_UNAUTHORIZED,
            )

        token_data = response.json()
        code = token_data["id_token"]

    oauth_keys = memory_service.get_memory(MemoryEnum.OAUTH_KEYS.value)

    if oauth_keys is None:
        raise ValidationError(
            "OAUTH KEYS não configurado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )
    keys = oauth_keys.value["keys"]

    token_headers = jwt.get_unverified_header(code)
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
            algorithms=["RS256", "HS256"],
            audience=[oauth_config["client_id"]],
        )
    except Exception as error:
        raise ValidationError(
            "OAUTH provider error: decode error",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        ) from error

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

    nh_user = _prepare_user(nh_user)

    permissions = Role.get_permissions_from_user(user=nh_user)
    features = (
        db.session.query(Memory)
        .filter(Memory.kind == MemoryEnum.FEATURES.value)
        .first()
    )

    if (
        features is None or FeatureEnum.OAUTH.value not in features.value
    ) and Permission.MAINTAINER not in permissions:
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
    """Get OAUTH configuration for the given schema"""
    schema_config = (
        db.session.query(SchemaConfig).filter(SchemaConfig.schemaName == schema).first()
    )

    if schema_config.config is not None and "oauth" in schema_config.config:
        oauth_config = schema_config.config["oauth"]

        oauth_config["redirect_uri"] = Config.MAIL_HOST + "/login-callback/" + schema
        oauth_config["auth_url"] += "&redirect_uri=" + urllib.parse.quote(
            oauth_config["redirect_uri"]
        )
        oauth_config["logout_url"] = Config.MAIL_HOST + "/login/" + schema

        return oauth_config

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
    if user is None:
        raise ValidationError(
            "Usuário inválido",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    if not user.active:
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


def _set_schema(schema):
    db_session = Session(db)
    result = db_session.execute(
        text("SELECT schema_name FROM information_schema.schemata")
    )

    schema_exists = False
    for r in result:
        if r[0] == schema:
            schema_exists = True

    if not schema_exists:
        raise ValidationError(
            "Schema Inexistente", "errors.invalidSchema", status.HTTP_400_BAD_REQUEST
        )

    db_session.close()

    dbSession.setSchema(schema)
