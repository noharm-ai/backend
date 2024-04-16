import re
from flask import Blueprint, request, render_template
from flask_jwt_extended import jwt_required, get_jwt_identity
from flask_jwt_extended import create_access_token, decode_token
from datetime import datetime, timedelta
from sqlalchemy import func
from flask import render_template, escape
from flask_mail import Message

from config import Config
from models.main import *
from models.appendix import *
from models.enums import UserAuditTypeEnum
from services import user_service
from .utils import tryCommit
from exception.validation_error import ValidationError

app_usr = Blueprint("app_usr", __name__)


@app_usr.route("/user", methods=["GET"])
@jwt_required()
def getUser():
    user = User.query.get(get_jwt_identity())

    if not user:
        return {
            "status": "error",
            "message": "Usuário Inexistente!",
        }, status.HTTP_400_BAD_REQUEST

    return {
        "status": "success",
        "data": {
            "id": user.id,
            "sign": user.config["sign"] if "sign" in user.config else "",
        },
    }, status.HTTP_200_OK


@app_usr.route("/user", methods=["PUT"])
@jwt_required()
def setUser():
    data = request.get_json()
    user = User.query.get(get_jwt_identity())

    if not user:
        return {
            "status": "error",
            "message": "Usuário Inexistente!",
        }, status.HTTP_400_BAD_REQUEST

    password = data.get("password", None)
    newpassword = data.get("newpassword", None)
    user = User.authenticate(user.email, password)

    if not user or not newpassword:
        return {
            "status": "error",
            "message": "Usuário Inexistente!",
        }, status.HTTP_400_BAD_REQUEST

    if not user_service.is_valid_password(newpassword):
        return {
            "status": "error",
            "message": "A senha deve possuir, no mínimo, 8 caracteres, letras maíusculas, minúsculas e números",
        }, status.HTTP_400_BAD_REQUEST

    update = {"password": func.crypt(newpassword, func.gen_salt("bf", 8))}
    db.session.query(User).filter(User.id == user.id).update(
        update, synchronize_session="fetch"
    )

    return tryCommit(db, user.id)


@app_usr.route("/user/forget", methods=["GET"])
def forgetPassword():
    email = request.args.get("email", None)
    user = User.query.filter_by(email=email).first()
    if not user:
        return {
            "status": "error",
            "message": "Usuário Inexistente!",
        }, status.HTTP_400_BAD_REQUEST

    expires = timedelta(hours=6)
    reset_token = create_access_token(identity=user.id, expires_delta=expires)

    audit_count = (
        db.session.query(UserAudit)
        .filter(UserAudit.idUser == user.id)
        .filter(UserAudit.auditType == UserAuditTypeEnum.FORGOT_PASSWORD.value)
        .filter(func.date(UserAudit.createdAt) == datetime.today().date())
        .count()
    )

    if audit_count > 5:
        return {
            "status": "error",
            "message": "O limite de requisições foi atingido.",
        }, status.HTTP_400_BAD_REQUEST

    user_service.create_audit(
        auditType=UserAuditTypeEnum.FORGOT_PASSWORD,
        id_user=user.id,
        responsible=user,
        pw_token=reset_token,
    )

    msg = Message()
    msg.subject = "NoHarm: Esqueci a senha"
    msg.sender = Config.MAIL_SENDER
    msg.recipients = [user.email]
    msg.html = render_template(
        "reset_email.html",
        user=user.name,
        email=user.email,
        token=reset_token,
        host=Config.MAIL_HOST,
    )
    mail.send(msg)

    db.session.commit()
    db.session.close()
    db.session.remove()

    return {
        "status": "success",
        "message": "Email enviado com sucesso para: " + escape(email),
    }, status.HTTP_200_OK


@app_usr.route("/user/reset", methods=["POST"])
def resetPassword():
    data = request.get_json()

    try:
        user_service.reset_password(
            token=data.get("reset_token", None),
            password=data.get("newpassword", None),
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, True)


@app_usr.route("/users/search", methods=["GET"])
@jwt_required()
def search_users():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    term = request.args.get("term", None)

    users = (
        User.query.filter(User.schema == user.schema)
        .filter(
            or_(
                ~User.config["roles"].astext.contains("suporte"),
                User.config["roles"] == None,
            )
        )
        .filter(User.name.ilike("%" + str(term) + "%"))
        .order_by(desc(User.active), asc(User.name))
        .all()
    )

    results = []
    for u in users:
        results.append({"id": u.id, "name": u.name})

    return {"status": "success", "data": results}, status.HTTP_200_OK
