from datetime import datetime
from sqlalchemy import func
from password_generator import PasswordGenerator
from flask import render_template
from typing import List

from models.main import User, db, UserAuthorization
from models.enums import FeatureEnum, UserAuditTypeEnum
from repository import user_repository
from services import memory_service, user_service
from utils import status
from config import Config
from utils import emailutils
from decorators.has_permission_decorator import has_permission, Permission
from exception.validation_error import ValidationError
from security.role import Role


@has_permission(Permission.READ_USERS)
def get_user_list(user_context: User):
    users = user_repository.get_admin_users_list(schema=user_context.schema)

    results = []
    for user in users:
        u = user[0]
        segments = user[1] if user[1] != None else []

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
    segments = segments = user_result[1] if user_result[1] != None else []

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
        "segments": segments,
    }


@has_permission(Permission.WRITE_USERS)
def upsert_user(data: dict, user_context: User, user_permissions: List[Permission]):
    idUser = data.get("id", None)
    id_segment_list = data.get("segments", [])

    if not idUser:
        userEmail = data.get("email", None)
        userName = data.get("name", None)

        if userEmail != None:
            userEmail = userEmail.lower()

        emailExists = user_repository.get_user_by_email(email=userEmail) != None

        if emailExists:
            raise ValidationError(
                "Já existe um usuário com este email",
                "errors.businessRules",
                status.HTTP_400_BAD_REQUEST,
            )

        newUser = User()
        newUser.email = userEmail
        newUser.name = userName
        newUser.external = data.get("external", None)
        newUser.active = bool(data.get("active", False))
        newUser.schema = user_context.schema
        pwo = PasswordGenerator()
        pwo.minlen = 6
        pwo.maxlen = 16
        password = pwo.generate()
        newUser.password = func.crypt(password, func.gen_salt("bf", 8))
        newUser.config = {"roles": data.get("roles", []), "features": []}

        if Permission.ADMIN_USERS in user_permissions:
            newUser.config["features"] = data.get("features", [])

        if memory_service.has_feature(FeatureEnum.OAUTH.value):
            template = "new_user_oauth.html"
        else:
            template = "new_user.html"

        if not _has_valid_roles(newUser.config["roles"]):
            raise ValidationError(
                "Papel inválido",
                "errors.businessRules",
                status.HTTP_400_BAD_REQUEST,
            )

        if not _has_valid_features(newUser.config.get("features", [])):
            raise ValidationError(
                "Feature inválida",
                "errors.businessRules",
                status.HTTP_400_BAD_REQUEST,
            )

        if len(newUser.config["roles"]) == 0:
            raise ValidationError(
                "O usuário deve ter ao menos um Papel definido",
                "errors.businessRules",
                status.HTTP_400_BAD_REQUEST,
            )

        db.session.add(newUser)
        db.session.flush()

        # authorizations
        _add_authorizations(
            id_segment_list=id_segment_list,
            user=newUser,
            responsible=user_context,
        )

        user_service.create_audit(
            auditType=UserAuditTypeEnum.CREATE,
            id_user=newUser.id,
            responsible=user_context,
            extra={"config": newUser.config, "segments": id_segment_list},
        )

        emailutils.sendEmail(
            "Boas-vindas NoHarm: Credenciais",
            Config.MAIL_SENDER,
            [userEmail],
            render_template(
                template,
                user=userName,
                email=userEmail,
                password=password,
                host=Config.MAIL_HOST,
                schema=user_context.schema,
            ),
        )

        return _get_user_data(newUser.id)
    else:
        updatedUser = db.session.query(User).filter(User.id == idUser).first()
        current_features = []
        new_roles = _remove_legacy_roles(data.get("roles", []))
        new_features = data.get("features", [])

        if updatedUser is None:
            raise ValidationError(
                "Usuário inexistente",
                "errors.businessRules",
                status.HTTP_400_BAD_REQUEST,
            )

        if updatedUser.schema != user_context.schema:
            raise ValidationError(
                "Usuário não autorizado",
                "errors.businessRules",
                status.HTTP_401_UNAUTHORIZED,
            )

        if updatedUser.config != None:
            current_features = updatedUser.config.get("features", [])

        updatedUser.name = data.get("name", None)
        updatedUser.external = data.get("external", None)
        updatedUser.active = bool(data.get("active", True))

        updatedUser.config = {"roles": new_roles}
        if Permission.ADMIN_USERS in user_permissions:
            updatedUser.config["features"] = new_features
        else:
            updatedUser.config["features"] = current_features

        if not _has_valid_roles(updatedUser.config.get("roles", [])):
            raise ValidationError(
                "Papel inválido",
                "errors.businessRules",
                status.HTTP_400_BAD_REQUEST,
            )

        if not _has_valid_features(updatedUser.config.get("features", [])):
            raise ValidationError(
                "Feature inválida",
                "errors.businessRules",
                status.HTTP_400_BAD_REQUEST,
            )

        if len(updatedUser.config.get("roles", [])) == 0:
            raise ValidationError(
                "O usuário deve ter ao menos um Papel definido",
                "errors.businessRules",
                status.HTTP_400_BAD_REQUEST,
            )

        db.session.add(updatedUser)
        db.session.flush()

        # authorizations
        _add_authorizations(
            id_segment_list=id_segment_list,
            user=updatedUser,
            responsible=user_context,
        )

        user_service.create_audit(
            auditType=UserAuditTypeEnum.UPDATE,
            id_user=updatedUser.id,
            responsible=user_context,
            extra={"config": updatedUser.config, "segments": id_segment_list},
        )

        return _get_user_data(updatedUser.id)


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

    permissions = Role.get_permissions_from_user(user=responsible)

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
