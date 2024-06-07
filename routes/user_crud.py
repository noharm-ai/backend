from password_generator import PasswordGenerator
from models.main import *
from models.appendix import *
from flask import Blueprint, request, render_template
from flask_jwt_extended import jwt_required, get_jwt_identity
from .utils import tryCommit, sendEmail
from sqlalchemy import func
from flask import render_template
from config import Config

from services import memory_service, user_service, user_admin_service
from models.enums import FeatureEnum, RoleEnum, UserAuditTypeEnum
from exception.validation_error import ValidationError


app_user_crud = Blueprint("app_user_crud", __name__)


def _has_special_role(roles):
    return (
        RoleEnum.ADMIN.value in roles
        or RoleEnum.SUPPORT.value in roles
        or RoleEnum.TRAINING.value in roles
        or RoleEnum.MULTI_SCHEMA.value in roles
    )


@app_user_crud.route("/editUser", methods=["POST"])
@jwt_required()
def createUser():
    data = request.get_json()
    user = User.find(get_jwt_identity())
    idUser = data.get("id", None)

    if not user:
        return {
            "status": "error",
            "message": "Usuário Inexistente!",
            "code": "errors.invalidUser",
        }, status.HTTP_400_BAD_REQUEST

    dbSession.setSchema(user.schema)

    roles = user.config["roles"] if user.config and "roles" in user.config else []
    if RoleEnum.USER_ADMIN.value not in roles:
        return {
            "status": "error",
            "message": "Usuário não autorizado",
            "code": "errors.unauthorizedUser",
        }, status.HTTP_401_UNAUTHORIZED

    if not idUser:
        userEmail = data.get("email", None)
        userName = data.get("name", None)

        if userEmail != None:
            userEmail = userEmail.lower()

        emailExists = User.findByEmail(userEmail) != None

        if emailExists:
            return {
                "status": "error",
                "message": "Já existe um usuário com este email!",
                "code": "errors.emailExists",
            }, status.HTTP_400_BAD_REQUEST

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

        if RoleEnum.ADMIN.value in roles or RoleEnum.TRAINING.value in roles:
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
            return {
                "status": "error",
                "message": "As permissões Administrador e Suporte não podem ser concedidas.",
                "code": "errors.unauthorizedUser",
            }, status.HTTP_401_UNAUTHORIZED

        db.session.add(newUser)
        db.session.flush()

        extra_audit = {
            "config": newUser.config,
        }
        user_service.create_audit(
            auditType=UserAuditTypeEnum.CREATE,
            id_user=newUser.id,
            responsible=user,
            extra=extra_audit,
        )

        user_result = user_admin_service.get_user_data(newUser.id)

        response, rstatus = tryCommit(db, user_result)

        if rstatus == status.HTTP_200_OK:
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

        return response
    else:
        updatedUser = User.query.get(idUser)

        if updatedUser is None:
            return {
                "status": "error",
                "message": "!Usuário Inexistente!",
                "code": "errors.invalidUser",
            }, status.HTTP_400_BAD_REQUEST

        if updatedUser.schema != user.schema:
            return {
                "status": "error",
                "message": "Usuário não autorizado",
                "code": "errors.unauthorizedUser",
            }, status.HTTP_401_UNAUTHORIZED

        updatedUser.name = data.get("name", None)
        updatedUser.external = data.get("external", None)
        updatedUser.active = bool(data.get("active", True))

        if RoleEnum.ADMIN.value in roles or RoleEnum.TRAINING.value in roles:
            if updatedUser.config is None:
                updatedUser.config = {"roles": data.get("roles", [])}
            else:
                newConfig = updatedUser.config.copy()
                newConfig["roles"] = data.get("roles", [])
                updatedUser.config = newConfig

        if updatedUser.config != None and "roles" in updatedUser.config:
            if _has_special_role(updatedUser.config["roles"]):
                return {
                    "status": "error",
                    "message": "As permissões Administrador e Suporte não podem ser concedidas.",
                    "code": "errors.unauthorizedUser",
                }, status.HTTP_401_UNAUTHORIZED

        extra_audit = {
            "config": updatedUser.config,
        }
        user_service.create_audit(
            auditType=UserAuditTypeEnum.UPDATE,
            id_user=updatedUser.id,
            responsible=user,
            extra=extra_audit,
        )

        db.session.add(updatedUser)
        db.session.flush()

        user_result = user_admin_service.get_user_data(updatedUser.id)

        return tryCommit(db, user_result)


@app_user_crud.route("/users", methods=["GET"])
@jwt_required()
def getUsers():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    try:
        result = user_admin_service.get_user_list(user=user)
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return {"status": "success", "data": result}, status.HTTP_200_OK


@app_user_crud.route("/user/reset-token", methods=["POST"])
@jwt_required()
def get_reset_token():
    data = request.get_json()

    try:
        token = user_service.admin_get_reset_token(data.get("idUser", None))
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, token)
