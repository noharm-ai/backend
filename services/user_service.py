import re
from datetime import datetime, timedelta

from flask import render_template, request
from flask_jwt_extended import create_access_token, decode_token
from flask_mail import Mail, Message
from sqlalchemy import asc, desc, func, or_

from config import Config
from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from models.appendix import SchemaConfig
from models.enums import UserAuditTypeEnum
from models.main import User, UserAudit, db
from repository import user_repository
from utils import status


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


@has_permission(Permission.ADMIN_USERS)
def admin_get_reset_token(id_user: int, user_context: User):
    reset_user = db.session.query(User).filter(User.id == id_user).first()
    if not reset_user:
        raise ValidationError(
            "Usuário inexistente.",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    return get_reset_token(
        email=reset_user.email, send_email=False, responsible=user_context
    )


def get_reset_token(email: str, send_email=True, responsible: User = None):
    user = (
        db.session.query(User)
        .filter(User.email == email)
        .filter(User.active == True)
        .first()
    )
    if not user:
        return

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
        raise ValidationError(
            "O limite de requisições foi atingido.",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    create_audit(
        auditType=UserAuditTypeEnum.FORGOT_PASSWORD,
        id_user=user.id,
        responsible=responsible if responsible != None else user,
        pw_token=reset_token,
    )

    if send_email:
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

        mail = Mail()
        mail.send(msg)

    return reset_token


@has_permission(Permission.WRITE_BASIC_FEATURES)
def update_password(password, newpassword, user_context: User):
    user = db.session.query(User).filter(User.id == user_context.id).first()

    if not user:
        raise ValidationError(
            "Usuário inexistente.",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    auth_user = user_repository.get_user_by_credentials(
        email=user.email, password=password
    )

    if not auth_user or not newpassword:
        raise ValidationError(
            "Usuário inexistente.",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    if not is_valid_password(newpassword):
        raise ValidationError(
            "A senha deve possuir, no mínimo, 8 caracteres, letras maíusculas, minúsculas e números",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    update = {"password": func.crypt(newpassword, func.gen_salt("bf", 8))}
    db.session.query(User).filter(User.id == user.id).update(
        update, synchronize_session="fetch"
    )

    create_audit(
        auditType=UserAuditTypeEnum.UPDATE_PASSWORD,
        id_user=user.id,
        responsible=user,
    )


@has_permission(Permission.READ_BASIC_FEATURES)
def search_users(user_context: User, term: str):
    users = (
        User.query.filter(User.schema == user_context.schema)
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

    return results


def validate_return_integration(user_context: User, user_permissions: list[Permission]):
    """
    Check if the user has an external ID for integration purposes.
    throws ValidationError if the user does not have an external ID
    """

    schema_config = (
        db.session.query(SchemaConfig)
        .filter(SchemaConfig.schemaName == user_context.schema)
        .first()
    )

    if schema_config.return_integration:
        current_user = db.session.query(User).filter(User.id == user_context.id).first()
        if current_user is None or not current_user.external:
            if Permission.WRITE_USERS in user_permissions:
                raise ValidationError(
                    "Usuário não possui ID externo para integração. Acesso o menu cadastro de usuários e insira o ID externo do seu usuário.",
                    "errors.businessError",
                    status.HTTP_400_BAD_REQUEST,
                )

            raise ValidationError(
                "Usuário não possui ID externo para integração. Solicite ao usuário responsável pelo cadastro que insira o ID externo do seu usuário.",
                "errors.businessError",
                status.HTTP_400_BAD_REQUEST,
            )
