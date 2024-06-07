from sqlalchemy import desc, func, or_, asc

from models.main import User, db, UserAuthorization
from services import permission_service
from utils import status

from exception.validation_error import ValidationError


def get_user_list(user: User):
    if not permission_service.is_user_admin(user):
        raise ValidationError(
            "Usuário não autorizado",
            "errors.businessRules",
            status.HTTP_401_UNAUTHORIZED,
        )

    segments_query = db.session.query(
        func.array_agg(UserAuthorization.idSegment)
    ).filter(User.id == UserAuthorization.idUser)

    users = (
        db.session.query(User, segments_query.scalar_subquery())
        .filter(User.schema == user.schema)
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
    for user in users:
        u = user[0]
        segments = user[1] if user[1] != None else []

        results.append(
            {
                "id": u.id,
                "external": u.external,
                "name": u.name,
                "email": u.email,
                "active": u.active,
                "roles": u.config["roles"] if u.config and "roles" in u.config else [],
                "segments": segments,
            }
        )

    return results


def get_user_data(id_user: int):
    segments_query = db.session.query(
        func.array_agg(UserAuthorization.idSegment)
    ).filter(User.id == UserAuthorization.idUser)

    user_result = (
        db.session.query(User, segments_query.as_scalar())
        .filter(User.id == id_user)
        .first()
    )

    user = user_result[0]
    segments = segments = user_result[1] if user_result[1] != None else []

    return {
        "id": user.id,
        "external": user.external,
        "name": user.name,
        "email": user.email,
        "active": user.active,
        "roles": user.config["roles"] if user.config and "roles" in user.config else [],
        "segments": segments,
    }
