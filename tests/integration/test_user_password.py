"""Integration tests for the user password lifecycle.

Covers the three endpoints a user goes through to change their password, none of
which had prior coverage:

* ``PUT /user`` — change the password while logged in (``update_password``)
* ``GET /user/forget`` — request a reset token (``get_reset_token``)
* ``POST /user/reset`` — consume the token (``reset_password``)
* ``POST /user-admin/reset-token`` — issue a token on the user's behalf
  (``admin_get_reset_token``)
* ``POST /user-admin/send-reset-email`` — email the reset link through Resend
  (``send_reset_password_email``)

Every write is audited in ``public.usuario_audit``; the tests assert the audit
trail as well as the effect on the stored password.

The test users live in the reserved ``>= 99000`` id range and use
``test...@noharm.ai`` e-mails, which the session-scoped ``clean_test_artifacts``
fixture removes afterwards.
"""

from unittest import mock

import pytest
from sqlalchemy import text

from config import Config
from models.enums import UserAuditTypeEnum
from security.role import Role
from tests.conftest import get_access, make_headers, session, session_commit

_USER_ID = 99001
_USER_EMAIL = "testpassword@noharm.ai"
_USER_PASSWORD = "InitialPass1"

_RATE_LIMITED_ID = 99002
_RATE_LIMITED_EMAIL = "testratelimit@noharm.ai"

_INACTIVE_ID = 99003
_INACTIVE_EMAIL = "testinactivepwd@noharm.ai"

_UNKNOWN_EMAIL = "testnobody@noharm.ai"

_NEW_PASSWORD = "ChangedPass9"
_WEAK_PASSWORD = "weak"

# Reset tokens a user can request per day before /user/forget starts refusing.
_DAILY_TOKEN_LIMIT = 6


def _upsert_user(id_user: int, email: str, password: str, active: bool = True) -> None:
    """Create (or reset) a test user with a known password."""
    session.execute(
        text(
            "INSERT INTO public.usuario"
            "  (idusuario, nome, email, senha, schema, fkusuario, config, ativo)"
            " VALUES"
            "  (:id, :name, :email, public.crypt(:password, public.gen_salt('bf', 8)),"
            "   'demo', :external, CAST(:config AS json), :active)"
            " ON CONFLICT (idusuario) DO UPDATE SET"
            "   senha = EXCLUDED.senha, email = EXCLUDED.email, ativo = EXCLUDED.ativo"
        ),
        {
            "id": id_user,
            "name": f"ZZTest User {id_user}",
            "email": email,
            "password": password,
            "external": str(id_user),
            "config": '{"roles": ["PRESCRIPTION_ANALYST"], "features": []}',
            "active": active,
        },
    )
    session_commit()


def _delete_audits(id_user: int) -> None:
    """Remove the audit trail of a test user."""
    session.execute(
        text("DELETE FROM public.usuario_audit WHERE idusuario = :id"), {"id": id_user}
    )
    session_commit()


def _audits(id_user: int, audit_type: UserAuditTypeEnum) -> list:
    """Return a user's audit rows of a given type, oldest first."""
    session_commit()
    return session.execute(
        text(
            "SELECT pw_token, created_by, audit_ip FROM public.usuario_audit"
            " WHERE idusuario = :id AND tp_audit = :type ORDER BY idusuario_audit"
        ),
        {"id": id_user, "type": audit_type.value},
    ).fetchall()


def _can_authenticate(client, email: str, password: str) -> bool:
    """Whether the credentials are accepted by /authenticate."""
    response = client.post("/authenticate", json={"email": email, "password": password})

    return response.status_code == 200


@pytest.fixture(scope="module", autouse=True)
def setup_password_users(clean_test_artifacts):  # noqa: ARG001
    """Create the module's users and drop their audit trail afterwards."""
    _upsert_user(_USER_ID, _USER_EMAIL, _USER_PASSWORD)
    _upsert_user(_RATE_LIMITED_ID, _RATE_LIMITED_EMAIL, _USER_PASSWORD)
    _upsert_user(_INACTIVE_ID, _INACTIVE_EMAIL, _USER_PASSWORD, active=False)

    yield

    for id_user in (_USER_ID, _RATE_LIMITED_ID, _INACTIVE_ID):
        _delete_audits(id_user)


@pytest.fixture
def user_headers(client):
    """Authenticate as the test user, restoring its known password first."""
    _upsert_user(_USER_ID, _USER_EMAIL, _USER_PASSWORD)

    return make_headers(
        get_access(
            client,
            email=_USER_EMAIL,
            password=_USER_PASSWORD,
            roles=[Role.PRESCRIPTION_ANALYST.value],
        )
    )


def test_update_password_changes_credentials_and_audits(client, user_headers):
    """PUT /user - a valid change replaces the password and records an audit entry"""
    _delete_audits(_USER_ID)

    response = client.put(
        "/user",
        headers=user_headers,
        json={"password": _USER_PASSWORD, "newpassword": _NEW_PASSWORD},
    )

    assert response.status_code == 200
    assert _can_authenticate(client, _USER_EMAIL, _NEW_PASSWORD)
    assert not _can_authenticate(client, _USER_EMAIL, _USER_PASSWORD)

    audits = _audits(_USER_ID, UserAuditTypeEnum.UPDATE_PASSWORD)
    assert len(audits) == 1
    # a logged-in change is self-issued and carries no reset token
    assert audits[0].created_by == _USER_ID
    assert audits[0].pw_token is None


def test_update_password_rejects_wrong_current_password(client, user_headers):
    """PUT /user - the current password must match [400 BAD REQUEST]"""
    response = client.put(
        "/user",
        headers=user_headers,
        json={"password": "NotMyPassword1", "newpassword": _NEW_PASSWORD},
    )

    assert response.status_code == 400
    assert _can_authenticate(client, _USER_EMAIL, _USER_PASSWORD)


def test_update_password_rejects_weak_new_password(client, user_headers):
    """PUT /user - the new password must satisfy the strength rule [400 BAD REQUEST]"""
    response = client.put(
        "/user",
        headers=user_headers,
        json={"password": _USER_PASSWORD, "newpassword": _WEAK_PASSWORD},
    )

    assert response.status_code == 400
    assert response.get_json()["code"] == "errors.businessRules"
    assert _can_authenticate(client, _USER_EMAIL, _USER_PASSWORD)


def test_update_password_rejects_missing_new_password(client, user_headers):
    """PUT /user - the new password is required [400 BAD REQUEST]"""
    response = client.put(
        "/user", headers=user_headers, json={"password": _USER_PASSWORD}
    )

    assert response.status_code == 400
    assert _can_authenticate(client, _USER_EMAIL, _USER_PASSWORD)


def test_forget_password_issues_a_token(client):
    """GET /user/forget - stores a reset token on a FORGOT_PASSWORD audit entry"""
    _upsert_user(_USER_ID, _USER_EMAIL, _USER_PASSWORD)
    _delete_audits(_USER_ID)

    response = client.get(f"/user/forget?email={_USER_EMAIL}")

    assert response.status_code == 200

    audits = _audits(_USER_ID, UserAuditTypeEnum.FORGOT_PASSWORD)
    assert len(audits) == 1
    assert audits[0].pw_token


def test_forget_password_is_silent_for_unknown_email(client):
    """GET /user/forget - an unknown e-mail answers 200 without leaking anything"""
    response = client.get(f"/user/forget?email={_UNKNOWN_EMAIL}")

    assert response.status_code == 200


def test_forget_password_is_silent_for_inactive_user(client):
    """GET /user/forget - an inactive user gets no token, but still answers 200"""
    _delete_audits(_INACTIVE_ID)

    response = client.get(f"/user/forget?email={_INACTIVE_EMAIL}")

    assert response.status_code == 200
    assert _audits(_INACTIVE_ID, UserAuditTypeEnum.FORGOT_PASSWORD) == []


def test_forget_password_enforces_daily_limit(client):
    """GET /user/forget - the 7th request on the same day is refused [400]"""
    _delete_audits(_RATE_LIMITED_ID)

    # get_reset_token counts the audits already stored for today and refuses when
    # that count is > 5. The count is taken before the current request is audited,
    # so the 6th request still sees only 5 predecessors and succeeds.
    for _ in range(_DAILY_TOKEN_LIMIT):
        response = client.get(f"/user/forget?email={_RATE_LIMITED_EMAIL}")
        assert response.status_code == 200

    response = client.get(f"/user/forget?email={_RATE_LIMITED_EMAIL}")

    assert response.status_code == 400
    assert response.get_json()["code"] == "errors.businessRules"
    # the refused request is not audited, so the trail stops at the last success
    assert (
        len(_audits(_RATE_LIMITED_ID, UserAuditTypeEnum.FORGOT_PASSWORD))
        == _DAILY_TOKEN_LIMIT
    )


def test_reset_password_consumes_the_token_once(client):
    """POST /user/reset - the token sets the new password and cannot be replayed"""
    _upsert_user(_USER_ID, _USER_EMAIL, _USER_PASSWORD)
    _delete_audits(_USER_ID)

    assert client.get(f"/user/forget?email={_USER_EMAIL}").status_code == 200
    token = _audits(_USER_ID, UserAuditTypeEnum.FORGOT_PASSWORD)[0].pw_token

    response = client.post(
        "/user/reset", json={"reset_token": token, "newpassword": _NEW_PASSWORD}
    )

    assert response.status_code == 200
    assert _can_authenticate(client, _USER_EMAIL, _NEW_PASSWORD)

    audits = _audits(_USER_ID, UserAuditTypeEnum.UPDATE_PASSWORD)
    assert len(audits) == 1
    assert audits[0].pw_token == token

    # replaying the same token is refused now that it is marked as used
    replay = client.post(
        "/user/reset", json={"reset_token": token, "newpassword": "AnotherPass8"}
    )

    assert replay.status_code == 400
    assert not _can_authenticate(client, _USER_EMAIL, "AnotherPass8")


def test_reset_password_rejects_weak_password(client):
    """POST /user/reset - the new password must satisfy the strength rule [400]"""
    _upsert_user(_USER_ID, _USER_EMAIL, _USER_PASSWORD)
    _delete_audits(_USER_ID)

    assert client.get(f"/user/forget?email={_USER_EMAIL}").status_code == 200
    token = _audits(_USER_ID, UserAuditTypeEnum.FORGOT_PASSWORD)[0].pw_token

    response = client.post(
        "/user/reset", json={"reset_token": token, "newpassword": _WEAK_PASSWORD}
    )

    assert response.status_code == 400
    assert _can_authenticate(client, _USER_EMAIL, _USER_PASSWORD)
    assert _audits(_USER_ID, UserAuditTypeEnum.UPDATE_PASSWORD) == []


def test_reset_password_rejects_unknown_token(client):
    """POST /user/reset - a token that was never issued is refused [400 BAD REQUEST]"""
    _upsert_user(_USER_ID, _USER_EMAIL, _USER_PASSWORD)
    _delete_audits(_USER_ID)

    # a syntactically valid token for this user, but with no matching audit entry
    forged = get_access(
        client,
        email=_USER_EMAIL,
        password=_USER_PASSWORD,
        roles=[Role.PRESCRIPTION_ANALYST.value],
    )

    response = client.post(
        "/user/reset", json={"reset_token": forged, "newpassword": _NEW_PASSWORD}
    )

    assert response.status_code == 400
    assert _can_authenticate(client, _USER_EMAIL, _USER_PASSWORD)


def test_reset_password_rejects_malformed_token(client):
    """POST /user/reset - an undecodable token is refused [401 UNAUTHORIZED]"""
    response = client.post(
        "/user/reset", json={"reset_token": "not-a-jwt", "newpassword": _NEW_PASSWORD}
    )

    assert response.status_code == 401
    assert response.get_json()["code"] == "errors.businessRules"


def test_reset_password_requires_both_parameters(client):
    """POST /user/reset - token and password are both required [400 BAD REQUEST]"""
    response = client.post("/user/reset", json={"newpassword": _NEW_PASSWORD})

    assert response.status_code == 400


def test_admin_reset_token_issues_a_token_for_another_user(client, admin_headers):
    """POST /user-admin/reset-token - an admin gets a usable token for another user"""
    _upsert_user(_USER_ID, _USER_EMAIL, _USER_PASSWORD)
    _delete_audits(_USER_ID)

    response = client.post(
        "/user-admin/reset-token", headers=admin_headers, json={"idUser": _USER_ID}
    )

    assert response.status_code == 200

    token = response.get_json()["data"]
    audits = _audits(_USER_ID, UserAuditTypeEnum.FORGOT_PASSWORD)
    assert len(audits) == 1
    assert audits[0].pw_token == token
    # the audit points at the admin who issued it, not at the target user
    assert audits[0].created_by != _USER_ID

    reset = client.post(
        "/user/reset", json={"reset_token": token, "newpassword": _NEW_PASSWORD}
    )

    assert reset.status_code == 200
    assert _can_authenticate(client, _USER_EMAIL, _NEW_PASSWORD)


def test_admin_reset_token_rejects_unknown_user(client, admin_headers):
    """POST /user-admin/reset-token - unknown user is rejected [400 BAD REQUEST]"""
    response = client.post(
        "/user-admin/reset-token", headers=admin_headers, json={"idUser": 99999}
    )

    assert response.status_code == 400
    assert response.get_json()["code"] == "errors.businessRules"


def test_admin_reset_token_requires_admin_users_permission(
    client, user_manager_headers
):
    """POST /user-admin/reset-token - USER_MANAGER is not enough [401 UNAUTHORIZED]"""
    response = client.post(
        "/user-admin/reset-token",
        headers=user_manager_headers,
        json={"idUser": _USER_ID},
    )

    assert response.status_code == 401


def _mock_resend_response(status_code: int = 200) -> mock.Mock:
    """Build a fake HTTP response for the Resend API."""
    response = mock.Mock()
    response.status_code = status_code
    response.json.return_value = {"id": "test-resend-email-id"}
    return response


def _send_reset_email(client, headers, id_user: int, resend_status: int = 200):
    """Call the send-reset-email endpoint with the Resend API mocked out."""
    with (
        mock.patch.object(Config, "RESEND_API_KEY", "test-api-key"),
        mock.patch(
            "services.email_service.requests.post",
            return_value=_mock_resend_response(resend_status),
        ) as post,
    ):
        response = client.post(
            "/user-admin/send-reset-email", headers=headers, json={"idUser": id_user}
        )

    return response, post


def test_send_reset_email_delivers_the_link(client, curator_headers):
    """POST /user-admin/send-reset-email - a curator emails a usable reset link"""
    _upsert_user(_USER_ID, _USER_EMAIL, _USER_PASSWORD)
    _delete_audits(_USER_ID)

    response, post = _send_reset_email(client, curator_headers, _USER_ID)

    assert response.status_code == 200
    assert response.get_json()["data"]["email"] == _USER_EMAIL

    audits = _audits(_USER_ID, UserAuditTypeEnum.FORGOT_PASSWORD)
    assert len(audits) == 1
    assert audits[0].pw_token
    # the audit points at the curator who sent it, not at the target user
    assert audits[0].created_by != _USER_ID

    post.assert_called_once()
    payload = post.call_args.kwargs["json"]
    assert payload["to"] == [_USER_EMAIL]
    # the delivered email carries the exact token that was audited
    assert audits[0].pw_token in payload["html"]

    reset = client.post(
        "/user/reset",
        json={"reset_token": audits[0].pw_token, "newpassword": _NEW_PASSWORD},
    )

    assert reset.status_code == 200
    assert _can_authenticate(client, _USER_EMAIL, _NEW_PASSWORD)


def test_send_reset_email_allows_admin(client, admin_headers):
    """POST /user-admin/send-reset-email - ADMIN can also send the email"""
    _upsert_user(_USER_ID, _USER_EMAIL, _USER_PASSWORD)
    _delete_audits(_USER_ID)

    response, post = _send_reset_email(client, admin_headers, _USER_ID)

    assert response.status_code == 200
    post.assert_called_once()


def test_send_reset_email_requires_permission(client, user_manager_headers):
    """POST /user-admin/send-reset-email - USER_MANAGER is not enough [401]"""
    response, post = _send_reset_email(client, user_manager_headers, _USER_ID)

    assert response.status_code == 401
    post.assert_not_called()


def test_send_reset_email_rejects_unknown_user(client, curator_headers):
    """POST /user-admin/send-reset-email - unknown user is rejected [400 BAD REQUEST]"""
    response, post = _send_reset_email(client, curator_headers, 99999)

    assert response.status_code == 400
    assert response.get_json()["code"] == "errors.businessRules"
    post.assert_not_called()


def test_send_reset_email_rejects_inactive_user(client, curator_headers):
    """POST /user-admin/send-reset-email - inactive user is rejected [400 BAD REQUEST]"""
    _delete_audits(_INACTIVE_ID)

    response, post = _send_reset_email(client, curator_headers, _INACTIVE_ID)

    assert response.status_code == 400
    post.assert_not_called()
    assert _audits(_INACTIVE_ID, UserAuditTypeEnum.FORGOT_PASSWORD) == []


def test_send_reset_email_surfaces_delivery_failure(client, curator_headers):
    """POST /user-admin/send-reset-email - a Resend error rolls back [502 BAD GATEWAY]"""
    _upsert_user(_USER_ID, _USER_EMAIL, _USER_PASSWORD)
    _delete_audits(_USER_ID)

    response, _ = _send_reset_email(client, curator_headers, _USER_ID, resend_status=422)

    assert response.status_code == 502
    assert response.get_json()["code"] == "errors.businessRules"
    # the failed send is rolled back, so no reset token is left behind
    assert _audits(_USER_ID, UserAuditTypeEnum.FORGOT_PASSWORD) == []


def test_send_reset_email_requires_configured_api_key(client, curator_headers):
    """POST /user-admin/send-reset-email - missing Resend key is refused [400]"""
    _upsert_user(_USER_ID, _USER_EMAIL, _USER_PASSWORD)
    _delete_audits(_USER_ID)

    with mock.patch.object(Config, "RESEND_API_KEY", ""):
        response = client.post(
            "/user-admin/send-reset-email",
            headers=curator_headers,
            json={"idUser": _USER_ID},
        )

    assert response.status_code == 400
    assert response.get_json()["code"] == "errors.businessRules"
