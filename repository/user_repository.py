"""Repository: User related operations"""

from typing import Iterable, Union, List
from sqlalchemy import Text, and_, func, or_, desc, asc, cast
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import aliased

from models.appendix import OrganizationSchema
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


def get_user_names(user_ids: Iterable[int | None]) -> dict[int, str]:
    """Names of the given users by id (None ids are ignored)"""
    ids = [i for i in user_ids if i is not None]
    if not ids:
        return {}

    return {
        u.id: u.name
        for u in db.session.query(User.id, User.name).filter(User.id.in_(ids)).all()
    }


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


def get_extra_schema_users_list(schema: str):
    """Get users from other schemas that were granted access to this schema
    through UserExtra, removing staff users"""
    # aliased so it does not correlate with the UserExtra in _remove_staff_users
    grant = aliased(UserExtra)
    grant_config = cast(grant.config, JSONB)
    # managers of every schema of the organization this schema belongs to
    # (usuario_extra.config['organization']['allSchemas'])
    organization_ids = (
        db.session.query(cast(OrganizationSchema.idOrganization, Text))
        .filter(OrganizationSchema.schemaName == schema)
        .scalar_subquery()
    )
    query = (
        db.session.query(User)
        .join(grant, grant.idUser == User.id)
        .filter(User.schema != schema)
        .filter(
            or_(
                # containment matches the exact schema name (a LIKE would let
                # "demo" match "demo2")
                grant_config["schemas"].contains([{"name": schema}]),
                and_(
                    grant_config["organization"].contains({"allSchemas": True}),
                    grant_config["organization"]["id"].astext == organization_ids,
                ),
            )
        )
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
