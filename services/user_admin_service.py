from datetime import datetime
from sqlalchemy import desc, func, or_, asc
from password_generator import PasswordGenerator
from flask import render_template


from models.main import User, db, UserAuthorization
from models.enums import RoleEnum, FeatureEnum, UserAuditTypeEnum
from services import permission_service, memory_service, user_service
from utils import status
from config import Config
from routes.utils import sendEmail

from exception.validation_error import ValidationError


def get_user_list(user: User):
    if not permission_service.is_user_admin(user):
        raise ValidationError(
            "Usuário não autorizado",
            "errors.businessRules",
            status.HTTP_401_UNAUTHORIZED,
        )

    segments_query = db.session.query(
        func.array_agg(UserAuthorization.idSegment)
    ).filter(User.id == UserAuthorization.idUser)

    users = (
        db.session.query(User, segments_query.scalar_subquery())
        .filter(User.schema == user.schema)
        .filter(
            or_(
                ~User.config["roles"].astext.contains("suporte"),
                User.config["roles"] == None,
            )
        )
        .order_by(desc(User.active), asc(User.name))
        .all()
    )

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
        "segments": segments,
    }


def upsert_user(data: dict, user: User):
    if not permission_service.is_user_admin(user):
        raise ValidationError(
            "Usuário não autorizado",
            "errors.businessRules",
            status.HTTP_401_UNAUTHORIZED,
        )

    idUser = data.get("id", None)
    id_segment_list = data.get("segments", [])
    roles = user.config["roles"] if user.config and "roles" in user.config else []

    if not idUser:
        userEmail = data.get("email", None)
        userName = data.get("name", None)

        if userEmail != None:
            userEmail = userEmail.lower()

        emailExists = User.findByEmail(userEmail) != None

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
        newUser.schema = user.schema
        pwo = PasswordGenerator()
        pwo.minlen = 6
        pwo.maxlen = 16
        password = pwo.generate()
        newUser.password = func.crypt(password, func.gen_salt("bf", 8))

        if permission_service.has_maintainer_permission(user):
            newUser.config = {"roles": data.get("roles", [])}
        else:
            newUserRoles = roles.copy()
            # remove administration roles
            try:
                newUserRoles.remove(RoleEnum.USER_ADMIN.value)
                newUserRoles.remove(RoleEnum.ADMIN.value)
                newUserRoles.remove(RoleEnum.SUPPORT.value)
                newUserRoles.remove(RoleEnum.TRAINING.value)
                newUserRoles.remove(RoleEnum.MULTI_SCHEMA.value)
            except ValueError:
                pass

            newUser.config = {"roles": newUserRoles}

        if memory_service.has_feature(FeatureEnum.OAUTH.value):
            template = "new_user_oauth.html"
        else:
            template = "new_user.html"

        if _has_special_role(newUser.config["roles"]):
            raise ValidationError(
                "As permissões Administrador e Suporte não podem ser concedidas.",
                "errors.unauthorizedUser",
                status.HTTP_401_UNAUTHORIZED,
            )

        db.session.add(newUser)
        db.session.flush()

        # authorizations
        _add_authorizations(
            id_segment_list=id_segment_list,
            user=newUser,
            responsible=user,
        )

        user_service.create_audit(
            auditType=UserAuditTypeEnum.CREATE,
            id_user=newUser.id,
            responsible=user,
            extra={"config": newUser.config, "segments": id_segment_list},
        )

        sendEmail(
            "Boas-vindas NoHarm: Credenciais",
            Config.MAIL_SENDER,
            [userEmail],
            render_template(
                template,
                user=userName,
                email=userEmail,
                password=password,
                host=Config.MAIL_HOST,
                schema=user.schema,
            ),
        )

        return _get_user_data(newUser.id)
    else:
        updatedUser = db.session.query(User).filter(User.id == idUser).first()

        if updatedUser is None:
            raise ValidationError(
                "Usuário inexistente",
                "errors.businessRules",
                status.HTTP_400_BAD_REQUEST,
            )

        if updatedUser.schema != user.schema:
            raise ValidationError(
                "Usuário não autorizado",
                "errors.businessRules",
                status.HTTP_401_UNAUTHORIZED,
            )

        updatedUser.name = data.get("name", None)
        updatedUser.external = data.get("external", None)
        updatedUser.active = bool(data.get("active", True))

        if permission_service.has_maintainer_permission(user):
            if updatedUser.config is None:
                updatedUser.config = {"roles": data.get("roles", [])}
            else:
                newConfig = updatedUser.config.copy()
                newConfig["roles"] = data.get("roles", [])
                updatedUser.config = newConfig

        if updatedUser.config != None and "roles" in updatedUser.config:
            if _has_special_role(updatedUser.config["roles"]):
                raise ValidationError(
                    "As permissões Administrador e Suporte não podem ser concedidas.",
                    "errors.businessRules",
                    status.HTTP_401_UNAUTHORIZED,
                )

        db.session.add(updatedUser)
        db.session.flush()

        # authorizations
        _add_authorizations(
            id_segment_list=id_segment_list,
            user=updatedUser,
            responsible=user,
        )

        user_service.create_audit(
            auditType=UserAuditTypeEnum.UPDATE,
            id_user=updatedUser.id,
            responsible=user,
            extra={"config": updatedUser.config, "segments": id_segment_list},
        )

        return _get_user_data(updatedUser.id)


def _has_special_role(roles):
    return (
        RoleEnum.ADMIN.value in roles
        or RoleEnum.SUPPORT.value in roles
        or RoleEnum.TRAINING.value in roles
        or RoleEnum.MULTI_SCHEMA.value in roles
    )


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

    for id_segment in id_segment_list:
        if str(
            id_segment
        ) not in valid_id_segment_list and not permission_service.has_maintainer_permission(
            responsible
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
