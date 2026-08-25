"""Repository: read queries over the public.usuario_audit table."""

from sqlalchemy import desc
from sqlalchemy.orm import aliased

from models.enums import UserAuditTypeEnum
from models.main import User, UserAudit, db


def get_reset_password_history(id_user: int, limit: int = 50):
    """List a user's FORGOT_PASSWORD audits with requester name and usage date.

    A reset token counts as used when an UPDATE_PASSWORD audit carrying the
    same pw_token exists (that is how reset_password marks tokens as spent).
    Returns tuples of (UserAudit, requester name, used-at datetime or None).
    """
    used_audit = aliased(UserAudit)
    responsible = aliased(User)

    return (
        db.session.query(UserAudit, responsible.name, used_audit.createdAt)
        .outerjoin(responsible, responsible.id == UserAudit.createdBy)
        .outerjoin(
            used_audit,
            (used_audit.pwToken == UserAudit.pwToken)
            & (used_audit.idUser == UserAudit.idUser)
            & (used_audit.auditType == UserAuditTypeEnum.UPDATE_PASSWORD.value),
        )
        .filter(UserAudit.idUser == id_user)
        .filter(UserAudit.auditType == UserAuditTypeEnum.FORGOT_PASSWORD.value)
        .order_by(desc(UserAudit.createdAt))
        .limit(limit)
        .all()
    )
