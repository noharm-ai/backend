from password_generator import PasswordGenerator
from models.main import *
from models.appendix import *
from flask import Blueprint, request, render_template
from flask_jwt_extended import jwt_required, get_jwt_identity
from .utils import tryCommit, sendEmail
from sqlalchemy import func, or_
from flask import render_template
from config import Config

from services import memory_service
from models.enums import FeatureEnum, RoleEnum


app_user_crud = Blueprint("app_user_crud", __name__)


def _has_special_role(roles):
    return (
        RoleEnum.ADMIN.value in roles
        or RoleEnum.SUPPORT.value in roles
        or RoleEnum.TRAINING.value in roles
        or RoleEnum.MULTI_SCHEMA.value in roles
    )


@app_user_crud.route("/editUser", methods=["PUT"])
@app_user_crud.route("/editUser/<int:idUser>", methods=["PUT"])
@jwt_required()
def createUser(idUser=None):
    data = request.get_json()
    user = User.find(get_jwt_identity())

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
        newUser.active = bool(data.get("active", True))
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

        response, rstatus = tryCommit(db, newUser.id)

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

            if RoleEnum.ADMIN.value in roles:
                # force password
                password = data.get("password", None)

                if password != None and password != "":
                    updatedUser.password = func.crypt(password, func.gen_salt("bf", 8))

        if updatedUser.config != None and "roles" in updatedUser.config:
            if _has_special_role(updatedUser.config["roles"]):
                return {
                    "status": "error",
                    "message": "As permissões Administrador e Suporte não podem ser concedidas.",
                    "code": "errors.unauthorizedUser",
                }, status.HTTP_401_UNAUTHORIZED

        db.session.add(updatedUser)
        db.session.flush()

        return tryCommit(db, updatedUser.id)


@app_user_crud.route("/users", methods=["GET"])
@jwt_required()
def getUsers():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    roles = user.config["roles"] if user.config and "roles" in user.config else []

    if "userAdmin" not in roles:
        return {
            "status": "error",
            "message": "Usuário não autorizado",
            "code": "errors.unauthorizedUser",
        }, status.HTTP_401_UNAUTHORIZED

    users = (
        User.query.filter(User.schema == user.schema)
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
    for u in users:
        results.append(
            {
                "id": u.id,
                "external": u.external,
                "name": u.name,
                "email": u.email,
                "active": u.active,
                "roles": u.config["roles"] if u.config and "roles" in u.config else [],
            }
        )

    return {"status": "success", "data": results}, status.HTTP_200_OK
