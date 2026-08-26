import random
import re
import time
from datetime import datetime, timedelta

from flask import render_template, request
from flask_jwt_extended import create_access_token, decode_token
from flask_mail import Mail, Message
from sqlalchemy import asc, desc, func, or_

from config import Config
from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from models.appendix import SchemaConfig
from models.enums import (
    UserAttributeEnum,
    UserAuditTypeEnum,
    UserOnboardingStatusEnum,
)
from models.main import User, UserAudit, db
from repository import (
    user_attribute_repository,
    user_audit_repository,
    user_repository,
)
from services import email_service
from utils import logger, status


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


@has_permission(Permission.READ_BASIC_FEATURES)
def complete_onboarding(user_context: User):
    """Mark the onboarding as done. Users without a pending onboarding are kept as is."""
    current_status = user_attribute_repository.get_value(
        id_user=user_context.id, kind=UserAttributeEnum.ONBOARDING.value
    )

    if current_status != UserOnboardingStatusEnum.PENDING.value:
        return

    user_attribute_repository.set_value(
        id_user=user_context.id,
        kind=UserAttributeEnum.ONBOARDING.value,
        value=UserOnboardingStatusEnum.ONBOARDED.value,
        responsible_id=user_context.id,
    )

    create_audit(
        auditType=UserAuditTypeEnum.UPDATE,
        id_user=user_context.id,
        responsible=user_context,
        extra={"onboarding": UserOnboardingStatusEnum.ONBOARDED.value},
    )


def reset_password(token: str, password: str):
    if token == None or password == None:
        raise ValidationError(
            "Parâmetros inválidos",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    try:
        user_token = decode_token(token)
    except Exception:
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


@has_permission(Permission.GENERATE_RESET_PASSWORD_LINK, Permission.ADMIN_USERS)
def admin_get_reset_token(id_user: int, user_context: User):
    # get_reset_token silently returns None for an inactive user, which would
    # surface as a link ending in /reset/null. Refuse explicitly instead, the
    # same way send_reset_password_email does.
    reset_user = (
        db.session.query(User)
        .filter(User.id == id_user)
        .filter(User.active == True)
        .first()
    )
    if not reset_user:
        raise ValidationError(
            "Usuário inexistente ou inativo.",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    # the manual link no longer requires a prior email attempt: the caller may
    # skip straight to it. What still guards the operation is the permission,
    # the caller retyping the registered address, and the audited trail below.
    return get_reset_token(
        email=reset_user.email,
        send_email=False,
        responsible=user_context,
        extra={"origin": "link"},
    )


@has_permission(Permission.SEND_RESET_PASSWORD_EMAIL)
def send_reset_password_email(id_user: int, user_context: User):
    """Generate a reset token and email its link to the user through ODOO."""
    reset_user = (
        db.session.query(User)
        .filter(User.id == id_user)
        .filter(User.active == True)
        .first()
    )
    if not reset_user:
        raise ValidationError(
            "Usuário inexistente ou inativo.",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    reset_token = get_reset_token(
        email=reset_user.email,
        send_email=False,
        responsible=user_context,
        extra={"origin": "email"},
    )

    try:
        email_service.send_email(
            to=[reset_user.email],
            subject="NoHarm: Redefinição de senha",
            html=render_template(
                "reset_email.html",
                user=reset_user.name,
                email=reset_user.email,
                token=reset_token,
                host=Config.MAIL_HOST,
            ),
        )
    except ValidationError as exception:
        if exception.httpStatus != status.HTTP_502_BAD_GATEWAY:
            raise

        # a delivery failure must not roll back the audit trail: the recorded
        # attempt unlocks the manual-link fallback and shows up in the history.
        # usuario_audit is insert-only, so the outcome is reported to the caller
        # rather than written back onto the row.
        return {"email": reset_user.email, "delivered": False}

    return {"email": reset_user.email, "delivered": True}


@has_permission(Permission.READ_RESET_PASSWORD_HISTORY)
def get_reset_password_history(id_user: int, user_context: User):
    """List a user's password reset requests, whether each link was used, and
    when the user last logged in (the audit trail's end-to-end success signal)."""
    reset_user = db.session.query(User).filter(User.id == id_user).first()
    if not reset_user or reset_user.schema != user_context.schema:
        raise ValidationError(
            "Usuário inexistente.",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    results = user_audit_repository.get_reset_password_history(id_user=id_user)
    last_login = user_audit_repository.get_last_login(id_user=id_user)

    history = []
    for audit, responsible_name, used_at in results:
        extra = audit.extra or {}
        history.append(
            {
                "requestedAt": audit.createdAt.isoformat() if audit.createdAt else None,
                "requestedBy": responsible_name,
                "origin": extra.get("origin"),
                "used": used_at is not None,
                "usedAt": used_at.isoformat() if used_at else None,
            }
        )

    return {
        "lastLogin": last_login.isoformat() if last_login else None,
        "history": history,
    }


def get_reset_token(
    email: str, send_email=True, responsible: User = None, extra: dict = None
):
    user = (
        db.session.query(User)
        .filter(User.email == email)
        .filter(User.active == True)
        .first()
    )
    if not user:
        time.sleep(random.uniform(0.5, 1.5))
        return

    expires = timedelta(hours=6)
    reset_token = create_access_token(identity=str(user.id), expires_delta=expires)

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

    # a new request less than one hour after the previous one usually means the
    # first email never reached the user, so the retry goes out through ODOO
    # instead of the default SMTP provider. Taken before create_audit: the
    # autoflush of the new row would otherwise make every request look like a
    # retry of itself.
    recent_attempt = send_email and (
        db.session.query(UserAudit)
        .filter(UserAudit.idUser == user.id)
        .filter(UserAudit.auditType == UserAuditTypeEnum.FORGOT_PASSWORD.value)
        .filter(UserAudit.createdAt > datetime.today() - timedelta(hours=1))
        .first()
        != None
    )

    create_audit(
        auditType=UserAuditTypeEnum.FORGOT_PASSWORD,
        id_user=user.id,
        responsible=responsible if responsible != None else user,
        pw_token=reset_token,
        extra=extra,
    )

    if send_email:
        html = render_template(
            "reset_email.html",
            user=user.name,
            email=user.email,
            token=reset_token,
            host=Config.MAIL_HOST,
        )

        if recent_attempt:
            try:
                email_service.send_email(
                    to=[user.email],
                    subject="NoHarm: Esqueci a senha",
                    html=html,
                )
            except ValidationError as exception:
                # this endpoint answers 200 to everyone on purpose (unknown
                # email, inactive user, success), so a delivery error must not
                # escape and turn into an account-enumeration signal. It would
                # also roll back the audit row that holds this token.
                logger.backend_logger.warning(
                    "Reset password: ODOO retry delivery failed for user %s: %s",
                    user.id,
                    exception,
                )
        else:
            msg = Message()
            msg.subject = "NoHarm: Esqueci a senha"
            msg.sender = Config.MAIL_SENDER
            msg.recipients = [user.email]
            msg.html = html

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
