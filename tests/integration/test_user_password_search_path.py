"""Password hashing must not depend on the connection's search_path.

pgcrypto lives in ``public``. A pooled connection may arrive with its
search_path pointing at a tenant schema (a trigger function that sets it at
session level and returns before resetting it), where an unqualified ``crypt``
or ``gen_salt`` does not resolve. The services that hash a password call the
functions qualified by ``public``, so they still work.

Each test runs the service directly on the app's ``db.session`` (the connection
that hashes), with ``SET search_path TO demo`` on it, and rolls everything back
at the end: no row of these tests is committed.
"""

from contextlib import contextmanager
from unittest import mock

import pytest
from flask_jwt_extended import create_access_token
from sqlalchemy import text

from mobile import app
from models.enums import UserAuditTypeEnum
from models.main import User, db
from security.role import Role
from services import user_admin_service, user_service

_MANAGER_ID = 99020
_MANAGER_EMAIL = "testsearchpathmanager@example.com"
_USER_ID = 99021
_USER_EMAIL = "testsearchpath@example.com"
_NEW_USER_EMAIL = "testsearchpathnew@example.com"

_PASSWORD = "InitialPass1"
_NEW_PASSWORD = "ChangedPass9"


@contextmanager
def _tenant_search_path():
    """Open a request on the app session with the search_path set to a tenant
    schema (pgcrypto off the path); roll back and reset it on the way out."""
    with app.test_request_context():
        db.session.connection(
            execution_options={"schema_translate_map": {None: "demo"}}
        )
        db.session.execute(text("SET search_path TO demo"))
        try:
            yield
        finally:
            db.session.rollback()
            db.session.execute(text("RESET search_path"))
            db.session.commit()
            db.session.remove()


def _insert_user(id_user: int, email: str, roles: list[str]) -> User:
    """Insert a test user with a known password in the current transaction."""
    db.session.execute(
        text(
            "INSERT INTO public.usuario"
            "  (idusuario, nome, email, senha, schema, fkusuario, config, ativo)"
            " VALUES"
            "  (:id, 'Fulano Beltrano', :email,"
            "   public.crypt(:password, public.gen_salt('bf', 8)),"
            "   'demo', :external, CAST(:config AS json), true)"
        ),
        {
            "id": id_user,
            "email": email,
            "password": _PASSWORD,
            "external": str(id_user),
            "config": '{"roles": ["%s"], "features": []}' % '", "'.join(roles),
        },
    )

    return db.session.get(User, id_user)


def _password_matches(email: str, password: str) -> bool:
    """Whether the stored hash of a user verifies the password with public.crypt."""
    return db.session.execute(
        text(
            "SELECT senha = public.crypt(:password, senha)"
            " FROM public.usuario WHERE email = :email"
        ),
        {"email": email, "password": password},
    ).scalar()


def _search_path() -> str:
    """The search_path of the session's connection."""
    return db.session.execute(text("SHOW search_path")).scalar()


def test_create_user_hashes_password_off_the_search_path():
    """upsert_user - a new user's password is hashed with pgcrypto off the path"""
    with _tenant_search_path():
        manager = _insert_user(_MANAGER_ID, _MANAGER_EMAIL, [Role.USER_MANAGER.value])
        assert _search_path() == "demo"

        with mock.patch(
            "services.user_admin_service.PasswordGenerator.generate",
            return_value=_PASSWORD,
        ):
            created = user_admin_service.upsert_user(
                data={
                    "email": _NEW_USER_EMAIL,
                    "name": "Ciclano de Tal",
                    "external": "testsearchpath",
                    "active": True,
                    "roles": [Role.PRESCRIPTION_ANALYST.value],
                },
                user_context=manager,
            )

        assert created["email"] == _NEW_USER_EMAIL
        assert _password_matches(_NEW_USER_EMAIL, _PASSWORD)


def test_update_password_hashes_password_off_the_search_path():
    """update_password - the new password is hashed with pgcrypto off the path"""
    with _tenant_search_path():
        user = _insert_user(_USER_ID, _USER_EMAIL, [Role.PRESCRIPTION_ANALYST.value])
        assert _search_path() == "demo"

        user_service.update_password(
            password=_PASSWORD, newpassword=_NEW_PASSWORD, user_context=user
        )

        assert _password_matches(_USER_EMAIL, _NEW_PASSWORD)


def test_reset_password_hashes_password_off_the_search_path():
    """reset_password - the reset password is hashed with pgcrypto off the path"""
    with _tenant_search_path():
        user = _insert_user(_USER_ID, _USER_EMAIL, [Role.PRESCRIPTION_ANALYST.value])
        token = create_access_token(identity=str(user.id))
        user_service.create_audit(
            auditType=UserAuditTypeEnum.FORGOT_PASSWORD,
            id_user=user.id,
            responsible=user,
            pw_token=token,
        )
        db.session.flush()
        assert _search_path() == "demo"

        user_service.reset_password(token=token, password=_NEW_PASSWORD)

        assert _password_matches(_USER_EMAIL, _NEW_PASSWORD)


@pytest.fixture(autouse=True)
def _no_user_left():
    """The tests roll back; make sure none of their users was committed."""
    yield

    with app.app_context():
        left = db.session.execute(
            text("SELECT count(*) FROM public.usuario WHERE email IN :emails"),
            {"emails": (_MANAGER_EMAIL, _USER_EMAIL, _NEW_USER_EMAIL)},
        ).scalar()
        db.session.remove()

    assert left == 0
