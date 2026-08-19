"""Repository: User related operations"""

from typing import Union, List
from sqlalchemy import func, or_, desc, asc

from models.main import db, User, UserAuthorization, UserExtra
from security.role import Role


def get_user_by_credentials(email: str, password: str) -> User:
    """Get user by email and password"""
    return (
        db.session.query(User)
        .filter(func.lower(User.email) == email.lower())
        .filter(User.password == func.public.crypt(password, User.password))
        .filter(User.active == True)
        .first()
    )


def get_user_by_email(email: str) -> User:
    """Get user by email"""
    return (
        db.session.query(User).filter(func.lower(User.email) == email.lower()).first()
    )


def get_users_by_role(schema: str, role: Union[Role, List[Role]]):
    """List users by role"""
    query = db.session.query(User).filter(User.schema == schema)

    # Handle single role or list of roles
    if isinstance(role, Role):
        # Single role - use existing logic
        query = query.filter(User.config["roles"].astext.contains(role.value))
    else:
        # Multiple roles - use OR logic to match ANY role
        role_conditions = [User.config["roles"].astext.contains(r.value) for r in role]
        query = query.filter(or_(*role_conditions))

    return query.filter(User.active == True).order_by(User.name).all()


STAFF_ROLES = [
    Role.ADMIN,
    Role.CURATOR,
    Role.RESEARCHER,
    Role.SERVICE_INTEGRATOR,
    Role.STATIC_USER,
    Role.TRAINING,
]


def _remove_staff_users(query):
    """Remove staff users from a User query. Staff roles may be set either in
    User.config or, out of band, in UserExtra"""
    extra_roles_query = (
        db.session.query(UserExtra)
        .filter(UserExtra.idUser == User.id)
        .filter(
            or_(
                *[
                    UserExtra.config["roles"].astext.contains(r.value)
                    for r in STAFF_ROLES
                ]
            )
        )
    )

    return query.filter(
        *[~User.config["roles"].astext.contains(r.value) for r in STAFF_ROLES]
    ).filter(~extra_roles_query.exists())


def get_admin_users_list(schema: str):
    """Get users list removing staff users"""
    segments_query = db.session.query(
        func.array_agg(UserAuthorization.idSegment)
    ).filter(User.id == UserAuthorization.idUser)

    query = db.session.query(User, segments_query.scalar_subquery()).filter(
        User.schema == schema
    )

    return _remove_staff_users(query).order_by(desc(User.active), asc(User.name)).all()


def get_active_users_by_role(schema: str, role: Role):
    """Get active users with the given role, removing staff users"""
    query = (
        db.session.query(User)
        .filter(User.schema == schema)
        .filter(User.active == True)
        .filter(User.config["roles"].astext.contains(role.value))
    )

    return _remove_staff_users(query).order_by(asc(User.name)).all()


def get_user_manager_list(schema: str):
    """Get active user managers, removing staff users"""
    return get_active_users_by_role(schema=schema, role=Role.USER_MANAGER)
