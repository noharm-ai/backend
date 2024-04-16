import re

from datetime import datetime
from flask_api import status
from flask import request
from flask_jwt_extended import decode_token
from sqlalchemy import desc, func

from models.main import User, UserAudit, db
from models.enums import UserAuditTypeEnum

from exception.validation_error import ValidationError


def create_audit(
    auditType: UserAuditTypeEnum,
    id_user: int,
    responsible: User,
    pw_token: str = None,
    extra: dict = None,
):
    if id_user == None:
        raise ValidationError(
            "Audit: Usuário inválido",
            "errors.unauthorizedUser",
            status.HTTP_400_BAD_REQUEST,
        )

    if responsible == None or responsible.id == None:
        raise ValidationError(
            "Audit: Usuário responsável inválido",
            "errors.unauthorizedUser",
            status.HTTP_400_BAD_REQUEST,
        )

    audit = UserAudit()
    audit.auditType = auditType.value
    audit.idUser = id_user
    audit.pwToken = pw_token
    audit.extra = extra
    audit.auditIp = request.remote_addr
    audit.createdBy = responsible.id
    audit.createdAt = datetime.today()

    db.session.add(audit)


def reset_password(token: str, password: str):
    if token == None or password == None:
        raise ValidationError(
            "Parâmetros inválidos",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    try:
        user_token = decode_token(token)
    except:
        raise ValidationError(
            "Token expirado. Você precisa fazer uma nova solicitação de troca de senha.",
            "errors.businessRules",
            status.HTTP_401_UNAUTHORIZED,
        )

    user_id = user_token["sub"]
    user = User.query.get(user_id)
    if not user:
        raise ValidationError(
            "Usuário inválido",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    if not is_valid_password(password):
        raise ValidationError(
            "A senha deve possuir, no mínimo, 8 caracteres, letras maíusculas, minúsculas e números",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    audit_token: UserAudit = (
        db.session.query(UserAudit)
        .filter(UserAudit.idUser == user.id)
        .filter(
            UserAudit.auditType.in_(
                [
                    UserAuditTypeEnum.FORGOT_PASSWORD.value,
                    UserAuditTypeEnum.UPDATE_PASSWORD.value,
                ]
            )
        )
        .filter(UserAudit.pwToken == token)
        .order_by(desc(UserAudit.createdAt))
        .first()
    )

    if (
        audit_token == None
        or audit_token.auditType == UserAuditTypeEnum.UPDATE_PASSWORD.value
    ):
        raise ValidationError(
            "O token não foi encontrado ou já foi utilizado",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    update = {"password": func.crypt(password, func.gen_salt("bf", 8))}
    db.session.query(User).filter(User.id == user.id).update(
        update, synchronize_session="fetch"
    )

    create_audit(
        auditType=UserAuditTypeEnum.UPDATE_PASSWORD,
        id_user=user.id,
        responsible=user,
        pw_token=token,
    )


def is_valid_password(password):
    return re.fullmatch(r"^(?=.*[A-Z])(?=.*[0-9])(?=.*[a-z]).{8,}$", password)
