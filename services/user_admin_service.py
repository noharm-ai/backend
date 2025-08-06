"""Service: user admin related operations"""

from datetime import datetime
from typing import List
from sqlalchemy import func
from password_generator import PasswordGenerator
from flask import render_template

from models.main import User, db, UserAuthorization
from models.appendix import SchemaConfig
from models.enums import FeatureEnum, UserAuditTypeEnum
from repository import user_repository
from services import memory_service, user_service, feature_service
from utils import status, emailutils
from config import Config
from decorators.has_permission_decorator import has_permission, Permission
from exception.validation_error import ValidationError
from security.role import Role


@has_permission(Permission.READ_USERS)
def get_user_list(user_context: User):
    """get users list, ignores staff users"""
    users = user_repository.get_admin_users_list(schema=user_context.schema)

    results = []
    for user in users:
        u = user[0]
        segments = user[1] if user[1] else []

        results.append(
            {
                "id": u.id,
                "external": u.external,
                "name": u.name,
                "email": u.email,
                "active": u.active,
                "roles": u.config["roles"] if u.config and "roles" in u.config else [],
                "features": (
                    u.config["features"] if u.config and "features" in u.config else []
                ),
                "ignoreReports": (
                    u.reports_config.get("ignore", []) if u.reports_config else []
                ),
                "segments": segments,
            }
        )

    return results


def _get_user_data(id_user: int):
    segments_query = db.session.query(
        func.array_agg(UserAuthorization.idSegment)
    ).filter(User.id == UserAuthorization.idUser)

    user_result = (
        db.session.query(User, segments_query.as_scalar())
        .filter(User.id == id_user)
        .first()
    )

    user = user_result[0]
    segments = segments = user_result[1] if user_result[1] else []

    return {
        "id": user.id,
        "external": user.external,
        "name": user.name,
        "email": user.email,
        "active": user.active,
        "roles": user.config["roles"] if user.config and "roles" in user.config else [],
        "features": (
            user.config["features"] if user.config and "features" in user.config else []
        ),
        "ignoreReports": (
            user.reports_config.get("ignore", []) if user.reports_config else []
        ),
        "segments": segments,
    }


@has_permission(Permission.WRITE_USERS)
def upsert_user(data: dict, user_context: User, user_permissions: List[Permission]):
    """upsert user"""
    id_user = data.get("id", None)
    id_segment_list = data.get("segments", [])

    schema_config = (
        db.session.query(SchemaConfig)
        .filter(SchemaConfig.schemaName == user_context.schema)
        .first()
    )

    external = data.get("external").strip() if data.get("external") else None

    if schema_config.return_integration and not external:
        if Permission.MAINTAINER not in user_permissions:
            raise ValidationError(
                "O campo ID Externo é de preenchimento obrigatório",
                "errors.businessRules",
                status.HTTP_400_BAD_REQUEST,
            )

    if not id_user:
        # add new user
        user_email = data.get("email", None)
        user_name = data.get("name", None)

        if user_email:
            user_email = user_email.lower()

        email_exists = user_repository.get_user_by_email(email=user_email)

        if email_exists:
            raise ValidationError(
                "Já existe um usuário com este email",
                "errors.businessRules",
                status.HTTP_400_BAD_REQUEST,
            )

        new_user = User()
        new_user.email = user_email
        new_user.name = user_name
        new_user.external = external
        new_user.active = bool(data.get("active", False))
        new_user.schema = user_context.schema
        pwo = PasswordGenerator()
        pwo.minlen = 6
        pwo.maxlen = 16
        password = pwo.generate()
        new_user.password = func.crypt(password, func.gen_salt("bf", 8))
        new_user.config = {"roles": data.get("roles", []), "features": []}
        new_user.reports_config = {"ignore": data.get("ignoreReports", [])}

        if Permission.ADMIN_USERS in user_permissions:
            new_user.config["features"] = data.get("features", [])

        if memory_service.has_feature(FeatureEnum.OAUTH.value):
            template = "new_user_oauth.html"
        else:
            template = "new_user.html"

        if not _has_valid_roles(new_user.config["roles"]):
            raise ValidationError(
                "Papel inválido",
                "errors.businessRules",
                status.HTTP_400_BAD_REQUEST,
            )

        if not _has_valid_features(new_user.config.get("features", [])):
            raise ValidationError(
                "Feature inválida",
                "errors.businessRules",
                status.HTTP_400_BAD_REQUEST,
            )

        if len(new_user.config["roles"]) == 0:
            raise ValidationError(
                "O usuário deve ter ao menos um Papel definido",
                "errors.businessRules",
                status.HTTP_400_BAD_REQUEST,
            )

        db.session.add(new_user)
        db.session.flush()

        # authorizations
        _add_authorizations(
            id_segment_list=id_segment_list,
            user=new_user,
            responsible=user_context,
        )

        user_service.create_audit(
            auditType=UserAuditTypeEnum.CREATE,
            id_user=new_user.id,
            responsible=user_context,
            extra={"config": new_user.config, "segments": id_segment_list},
        )

        emailutils.sendEmail(
            "Boas-vindas NoHarm: Credenciais",
            Config.MAIL_SENDER,
            [user_email],
            render_template(
                template,
                user=user_name,
                email=user_email,
                password=password,
                host=Config.MAIL_HOST,
                schema=user_context.schema,
            ),
        )

        return _get_user_data(new_user.id)

    # update user
    updated_user = db.session.query(User).filter(User.id == id_user).first()
    current_features = []
    new_roles = _remove_legacy_roles(data.get("roles", []))
    new_features = data.get("features", [])

    if updated_user is None:
        raise ValidationError(
            "Usuário inexistente",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    if updated_user.schema != user_context.schema:
        raise ValidationError(
            "Usuário não autorizado",
            "errors.businessRules",
            status.HTTP_401_UNAUTHORIZED,
        )

    if updated_user.config:
        current_features = updated_user.config.get("features", [])

    updated_user.name = data.get("name", None)
    updated_user.external = external
    updated_user.active = bool(data.get("active", True))
    updated_user.reports_config = {"ignore": data.get("ignoreReports", [])}

    updated_user.config = {"roles": new_roles}
    if Permission.ADMIN_USERS in user_permissions:
        updated_user.config["features"] = new_features
    else:
        updated_user.config["features"] = current_features

    if not _has_valid_roles(updated_user.config.get("roles", [])):
        raise ValidationError(
            "Papel inválido",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    if not _has_valid_features(updated_user.config.get("features", [])):
        raise ValidationError(
            "Feature inválida",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    if len(updated_user.config.get("roles", [])) == 0:
        raise ValidationError(
            "O usuário deve ter ao menos um Papel definido",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    db.session.add(updated_user)
    db.session.flush()

    # authorizations
    _add_authorizations(
        id_segment_list=id_segment_list,
        user=updated_user,
        responsible=user_context,
    )

    user_service.create_audit(
        auditType=UserAuditTypeEnum.UPDATE,
        id_user=updated_user.id,
        responsible=user_context,
        extra={"config": updated_user.config, "segments": id_segment_list},
    )

    return _get_user_data(updated_user.id)


def _remove_legacy_roles(roles):
    legacy_roles = [
        "alert-bt",
        "beta-cards",
        "care",
        "concilia",
        "cpoe",
        "doctor",
        "noimit",
        "nolimit",
        "oauth-test",
        "prescriptionEdit",
        "presmed-form",
        "readonly",
        "service-user",
        "staging",
        "summary",
        "suporte",
        "transcription",
        "userAdmin",
    ]

    for lr in legacy_roles:
        if lr in roles:
            roles.remove(lr)

    return roles


def _has_valid_roles(roles):
    valid_roles = [
        Role.PRESCRIPTION_ANALYST.value,
        Role.CONFIG_MANAGER.value,
        Role.DISCHARGE_MANAGER.value,
        Role.USER_MANAGER.value,
        Role.VIEWER.value,
        Role.DISPENSING_MANAGER.value,
        Role.REGULATOR.value,
    ]

    for r in roles:
        if r not in valid_roles:
            return False

    return True


def _has_valid_features(features):
    valid_features = [FeatureEnum.DISABLE_CPOE.value, FeatureEnum.STAGING_ACCESS.value]

    for f in features:
        if f not in valid_features:
            return False

    return True


def _add_authorizations(id_segment_list, user: User, responsible: User):
    permissions = Role.get_permissions_from_user(user=responsible)
    has_auth_segment_feature = feature_service.has_feature(
        FeatureEnum.AUTHORIZATION_SEGMENT
    )

    if not has_auth_segment_feature and Permission.MAINTAINER not in permissions:
        return False

    # remove old authorizations
    db.session.query(UserAuthorization).filter(
        UserAuthorization.idUser == user.id
    ).filter(UserAuthorization.idSegment != None).delete()

    # responsible authorizations
    responsible_auth_list = (
        db.session.query(UserAuthorization)
        .filter(UserAuthorization.idUser == responsible.id)
        .all()
    )
    valid_id_segment_list = {}
    for a in responsible_auth_list:
        valid_id_segment_list[str(a.idSegment)] = True

    for id_segment in id_segment_list:
        if (
            str(id_segment) not in valid_id_segment_list
            and Permission.MAINTAINER not in permissions
        ):
            raise ValidationError(
                f"Permissão inválida no segmento {id_segment}",
                "errors.businessRules",
                status.HTTP_401_UNAUTHORIZED,
            )

        authorization = UserAuthorization()
        authorization.idUser = user.id
        authorization.idSegment = id_segment
        authorization.createdAt = datetime.today()
        authorization.createdBy = responsible.id

        db.session.add(authorization)
        db.session.flush()
