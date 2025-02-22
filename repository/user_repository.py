"""Repository: User related operations"""

from sqlalchemy import func, or_, desc, asc

from models.main import db, User, UserAuthorization, UserExtra
from security.role import Role


def get_user_by_credentials(email: str, password: str) -> User:
    """Get user by email and password"""
    return (
        db.session.query(User)
        .filter(func.lower(User.email) == email.lower())
        .filter(User.password == func.crypt(password, User.password))
        .filter(User.active == True)
        .first()
    )


def get_user_by_email(email: str) -> User:
    """Get user by email"""
    return (
        db.session.query(User).filter(func.lower(User.email) == email.lower()).first()
    )


def get_admin_users_list(schema: str):
    """Get users list removing staff users"""
    segments_query = db.session.query(
        func.array_agg(UserAuthorization.idSegment)
    ).filter(User.id == UserAuthorization.idUser)

    extra_roles_query = (
        db.session.query(UserExtra)
        .filter(UserExtra.idUser == User.id)
        .filter(
            or_(
                UserExtra.config["roles"].astext.contains(Role.ADMIN.value),
                UserExtra.config["roles"].astext.contains(Role.CURATOR.value),
                UserExtra.config["roles"].astext.contains(Role.RESEARCHER.value),
                UserExtra.config["roles"].astext.contains(
                    Role.SERVICE_INTEGRATOR.value
                ),
                UserExtra.config["roles"].astext.contains(Role.STATIC_USER.value),
            )
        )
    )

    users = (
        db.session.query(User, segments_query.scalar_subquery())
        .filter(User.schema == schema)
        .filter(
            ~User.config["roles"].astext.contains(Role.ADMIN.value),
            ~User.config["roles"].astext.contains(Role.CURATOR.value),
            ~User.config["roles"].astext.contains(Role.RESEARCHER.value),
            ~User.config["roles"].astext.contains(Role.SERVICE_INTEGRATOR.value),
            ~User.config["roles"].astext.contains(Role.STATIC_USER.value),
        )
        .filter(~extra_roles_query.exists())
        .order_by(desc(User.active), asc(User.name))
        .all()
    )

    return users
