"""Integration tests for the user password lifecycle.

Covers the three endpoints a user goes through to change their password, none of
which had prior coverage:

* ``PUT /user`` — change the password while logged in (``update_password``)
* ``GET /user/forget`` — request a reset token (``get_reset_token``)
* ``POST /user/reset`` — consume the token (``reset_password``)
* ``POST /user-admin/reset-token`` — issue a token on the user's behalf
  (``admin_get_reset_token``)
* ``POST /user-admin/send-reset-email`` — email the reset link through ODOO
  (``send_reset_password_email``)
* ``GET /user-admin/reset-history/<id>`` — reset request history with usage
  status (``get_reset_password_history``)

Every write is audited in ``public.usuario_audit``; the tests assert the audit
trail as well as the effect on the stored password.

The test users live in the reserved ``>= 99000`` id range and use
``test...@example.com`` e-mails, which the session-scoped ``clean_test_artifacts``
fixture removes afterwards.
"""

import xmlrpc.client
from unittest import mock

import pytest
from sqlalchemy import text

from config import Config
from models.enums import UserAuditTypeEnum
from security.role import Role
from tests.conftest import get_access, make_headers, session, session_commit

_USER_ID = 99001
_USER_EMAIL = "testpassword@example.com"
_USER_PASSWORD = "InitialPass1"

_RATE_LIMITED_ID = 99002
_RATE_LIMITED_EMAIL = "testratelimit@example.com"

_INACTIVE_ID = 99003
_INACTIVE_EMAIL = "testinactivepwd@example.com"

_UNKNOWN_EMAIL = "testnobody@example.com"

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
            "SELECT pw_token, created_by, audit_ip, extra FROM public.usuario_audit"
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
    assert audits[0].extra == {"origin": "self"}


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
    # requests 2..6 land inside the one-hour retry window and are handed to
    # email_service, which refuses because ODOO is not configured here. That
    # error is swallowed on purpose, so they still answer 200.
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
    assert audits[0].extra == {"origin": "link"}
    # the audit points at the admin who issued it, not at the target user
    assert audits[0].created_by != _USER_ID

    reset = client.post(
        "/user/reset", json={"reset_token": token, "newpassword": _NEW_PASSWORD}
    )

    assert reset.status_code == 200
    assert _can_authenticate(client, _USER_EMAIL, _NEW_PASSWORD)


def test_admin_reset_token_needs_no_prior_email_attempt(client, admin_headers):
    """POST /user-admin/reset-token - the email step may be skipped entirely"""
    _upsert_user(_USER_ID, _USER_EMAIL, _USER_PASSWORD)
    _delete_audits(_USER_ID)

    response = client.post(
        "/user-admin/reset-token", headers=admin_headers, json={"idUser": _USER_ID}
    )

    assert response.status_code == 200
    assert [a.extra for a in _audits(_USER_ID, UserAuditTypeEnum.FORGOT_PASSWORD)] == [
        {"origin": "link"}
    ]


def test_admin_reset_token_allows_curator(client, curator_headers):
    """POST /user-admin/reset-token - CURATOR generates the link without ADMIN_USERS"""
    _upsert_user(_USER_ID, _USER_EMAIL, _USER_PASSWORD)
    _delete_audits(_USER_ID)

    response = client.post(
        "/user-admin/reset-token", headers=curator_headers, json={"idUser": _USER_ID}
    )

    assert response.status_code == 200

    token = response.get_json()["data"]
    reset = client.post(
        "/user/reset", json={"reset_token": token, "newpassword": _NEW_PASSWORD}
    )

    assert reset.status_code == 200
    assert _can_authenticate(client, _USER_EMAIL, _NEW_PASSWORD)


def test_admin_reset_token_after_an_email_attempt(client, admin_headers):
    """POST /user-admin/reset-token - both attempts are audited separately"""
    _upsert_user(_USER_ID, _USER_EMAIL, _USER_PASSWORD)
    _delete_audits(_USER_ID)

    sent, _, _ = _send_reset_email(client, admin_headers, _USER_ID)
    assert sent.get_json()["data"]["delivered"] is True

    response = client.post(
        "/user-admin/reset-token", headers=admin_headers, json={"idUser": _USER_ID}
    )

    assert response.status_code == 200

    audits = _audits(_USER_ID, UserAuditTypeEnum.FORGOT_PASSWORD)
    assert [a.extra for a in audits] == [{"origin": "email"}, {"origin": "link"}]


def test_admin_reset_token_rejects_unknown_user(client, admin_headers):
    """POST /user-admin/reset-token - unknown user is rejected [400 BAD REQUEST]"""
    response = client.post(
        "/user-admin/reset-token", headers=admin_headers, json={"idUser": 99999}
    )

    assert response.status_code == 400
    assert response.get_json()["code"] == "errors.businessRules"


def test_admin_reset_token_rejects_inactive_user(client, admin_headers):
    """POST /user-admin/reset-token - an inactive user is refused [400 BAD REQUEST]"""
    _delete_audits(_INACTIVE_ID)

    response = client.post(
        "/user-admin/reset-token", headers=admin_headers, json={"idUser": _INACTIVE_ID}
    )

    assert response.status_code == 400
    assert response.get_json()["code"] == "errors.businessRules"
    assert _audits(_INACTIVE_ID, UserAuditTypeEnum.FORGOT_PASSWORD) == []


def test_admin_reset_token_requires_the_link_permission(
    client, user_manager_headers
):
    """POST /user-admin/reset-token - USER_MANAGER lacks the link permission [401]"""
    response = client.post(
        "/user-admin/reset-token",
        headers=user_manager_headers,
        json={"idUser": _USER_ID},
    )

    assert response.status_code == 401


class _OdooEmailStub:
    """Fake ODOO execute callable that records the mail.mail calls it receives."""

    def __init__(
        self,
        create_result: int = 101,
        send_fault: bool = False,
        send_fault_string: str = "delivery refused",
    ):
        self.calls = []
        self.create_result = create_result
        self.send_fault = send_fault
        self.send_fault_string = send_fault_string

    def __call__(self, model, action, payload, options):
        self.calls.append((model, action, payload, options))
        if action == "create":
            return self.create_result
        if action == "send" and self.send_fault:
            raise xmlrpc.client.Fault(1, self.send_fault_string)
        return True

    def created_mail(self) -> dict:
        """Return the values dict passed to the mail.mail create call."""
        return next(c[2][0] for c in self.calls if c[1] == "create")


def _send_reset_email(
    client, headers, id_user: int, stub: _OdooEmailStub = None, unreachable: bool = False
):
    """Call the send-reset-email endpoint with the ODOO client mocked out."""
    stub = stub if stub is not None else _OdooEmailStub()

    with (
        mock.patch.object(Config, "ODOO_API_URL", "http://odoo.test/"),
        mock.patch(
            "services.email_service.odoo_client.get_client",
            return_value=None if unreachable else stub,
        ) as get_client,
    ):
        response = client.post(
            "/user-admin/send-reset-email", headers=headers, json={"idUser": id_user}
        )

    return response, stub, get_client


def test_send_reset_email_delivers_the_link(client, curator_headers):
    """POST /user-admin/send-reset-email - a curator emails a usable reset link"""
    _upsert_user(_USER_ID, _USER_EMAIL, _USER_PASSWORD)
    _delete_audits(_USER_ID)

    response, stub, _ = _send_reset_email(client, curator_headers, _USER_ID)

    assert response.status_code == 200
    assert response.get_json()["data"] == {"email": _USER_EMAIL, "delivered": True}

    audits = _audits(_USER_ID, UserAuditTypeEnum.FORGOT_PASSWORD)
    assert len(audits) == 1
    assert audits[0].pw_token
    assert audits[0].extra == {"origin": "email"}
    # the audit points at the curator who sent it, not at the target user
    assert audits[0].created_by != _USER_ID

    mail = stub.created_mail()
    assert mail["email_to"] == _USER_EMAIL
    # the delivered email carries the exact token that was audited
    assert audits[0].pw_token in mail["body_html"]
    # the created mail.mail record is the one told to send
    assert ("mail.mail", "send", [[stub.create_result]]) in [
        c[:3] for c in stub.calls
    ]

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

    response, stub, _ = _send_reset_email(client, admin_headers, _USER_ID)

    assert response.status_code == 200
    assert stub.created_mail()["email_to"] == _USER_EMAIL


def test_send_reset_email_requires_permission(client, user_manager_headers):
    """POST /user-admin/send-reset-email - USER_MANAGER is not enough [401]"""
    response, _, get_client = _send_reset_email(
        client, user_manager_headers, _USER_ID
    )

    assert response.status_code == 401
    get_client.assert_not_called()


def test_send_reset_email_rejects_unknown_user(client, curator_headers):
    """POST /user-admin/send-reset-email - unknown user is rejected [400 BAD REQUEST]"""
    response, _, get_client = _send_reset_email(client, curator_headers, 99999)

    assert response.status_code == 400
    assert response.get_json()["code"] == "errors.businessRules"
    get_client.assert_not_called()


def test_send_reset_email_rejects_inactive_user(client, curator_headers):
    """POST /user-admin/send-reset-email - inactive user is rejected [400 BAD REQUEST]"""
    _delete_audits(_INACTIVE_ID)

    response, _, get_client = _send_reset_email(client, curator_headers, _INACTIVE_ID)

    assert response.status_code == 400
    get_client.assert_not_called()
    assert _audits(_INACTIVE_ID, UserAuditTypeEnum.FORGOT_PASSWORD) == []


def test_send_reset_email_records_unreachable_odoo(client, curator_headers):
    """POST /user-admin/send-reset-email - an ODOO timeout keeps the audited attempt"""
    _upsert_user(_USER_ID, _USER_EMAIL, _USER_PASSWORD)
    _delete_audits(_USER_ID)

    response, _, _ = _send_reset_email(client, curator_headers, _USER_ID, unreachable=True)

    assert response.status_code == 200
    assert response.get_json()["data"] == {"email": _USER_EMAIL, "delivered": False}

    # the failed attempt stays audited: it unlocks the manual-link fallback and
    # shows up in the reset history
    audits = _audits(_USER_ID, UserAuditTypeEnum.FORGOT_PASSWORD)
    assert len(audits) == 1
    assert audits[0].extra == {"origin": "email"}


def test_send_reset_email_records_delivery_failure(client, curator_headers):
    """POST /user-admin/send-reset-email - an ODOO send fault keeps the audited attempt"""
    _upsert_user(_USER_ID, _USER_EMAIL, _USER_PASSWORD)
    _delete_audits(_USER_ID)

    response, _, _ = _send_reset_email(
        client, curator_headers, _USER_ID, stub=_OdooEmailStub(send_fault=True)
    )

    assert response.status_code == 200
    assert response.get_json()["data"]["delivered"] is False

    audits = _audits(_USER_ID, UserAuditTypeEnum.FORGOT_PASSWORD)
    assert len(audits) == 1
    assert audits[0].extra == {"origin": "email"}


# ODOO encodes RPC replies with allow_none=False and mail.mail.send() returns
# None, so a successful send is reported back to us as a fault raised while
# serialising the response. Trimmed to the frames that identify it.
_NONE_REPLY_TRACEBACK = """Traceback (most recent call last):
  File "/home/odoo/src/odoo/saas-19.3/addons/rpc/controllers/xmlrpc.py", line 137, in _xmlrpc
    return dumps((result,))
  File "/home/odoo/src/odoo/saas-19.3/addons/rpc/controllers/xmlrpc.py", line 116, in dumps
    response = OdooMarshaller(allow_none=False).dumps(params)
  File "/usr/lib/python3.12/xmlrpc/client.py", line 540, in dump_nil
    raise TypeError("cannot marshal None unless allow_none is enabled")
TypeError: cannot marshal None unless allow_none is enabled
"""


def test_send_reset_email_treats_the_empty_send_reply_as_delivered(
    client, curator_headers
):
    """POST /user-admin/send-reset-email - ODOO's unencodable None reply is not a failure"""
    _upsert_user(_USER_ID, _USER_EMAIL, _USER_PASSWORD)
    _delete_audits(_USER_ID)

    response, stub, _ = _send_reset_email(
        client,
        curator_headers,
        _USER_ID,
        stub=_OdooEmailStub(send_fault=True, send_fault_string=_NONE_REPLY_TRACEBACK),
    )

    # the send ran and committed on the ODOO side before the reply failed to
    # encode, so the mail really was delivered
    assert response.status_code == 200
    assert response.get_json()["data"] == {"email": _USER_EMAIL, "delivered": True}

    audits = _audits(_USER_ID, UserAuditTypeEnum.FORGOT_PASSWORD)
    assert len(audits) == 1
    assert audits[0].extra == {"origin": "email"}
    assert [c[1] for c in stub.calls] == ["create", "send"]


def test_reset_history_shows_requests_and_usage(client, curator_headers):
    """GET /user-admin/reset-history - lists attempts with origin and usage status"""
    _upsert_user(_USER_ID, _USER_EMAIL, _USER_PASSWORD)
    _delete_audits(_USER_ID)

    send, _, _ = _send_reset_email(client, curator_headers, _USER_ID)
    assert send.status_code == 200

    token = _audits(_USER_ID, UserAuditTypeEnum.FORGOT_PASSWORD)[0].pw_token
    reset = client.post(
        "/user/reset", json={"reset_token": token, "newpassword": _NEW_PASSWORD}
    )
    assert reset.status_code == 200

    response = client.get(
        f"/user-admin/reset-history/{_USER_ID}", headers=curator_headers
    )

    assert response.status_code == 200

    rows = response.get_json()["data"]["history"]
    assert len(rows) == 1
    assert rows[0]["origin"] == "email"
    assert "delivered" not in rows[0]
    assert rows[0]["requestedBy"]
    assert rows[0]["used"] is True
    assert rows[0]["usedAt"]
    # the reset token itself must never leave the backend through the history
    assert "pw_token" not in rows[0] and "token" not in rows[0]


def test_reset_history_shows_pending_requests(client, curator_headers):
    """GET /user-admin/reset-history - an unused link shows as not used"""
    _upsert_user(_USER_ID, _USER_EMAIL, _USER_PASSWORD)
    _delete_audits(_USER_ID)

    send, _, _ = _send_reset_email(client, curator_headers, _USER_ID, unreachable=True)
    assert send.status_code == 200

    response = client.get(
        f"/user-admin/reset-history/{_USER_ID}", headers=curator_headers
    )

    assert response.status_code == 200

    rows = response.get_json()["data"]["history"]
    assert len(rows) == 1
    assert rows[0]["origin"] == "email"
    assert "delivered" not in rows[0]
    assert rows[0]["used"] is False
    assert rows[0]["usedAt"] is None


def test_reset_history_reports_the_last_login(client, curator_headers):
    """GET /user-admin/reset-history - the last LOGIN audit is the success signal"""
    _upsert_user(_USER_ID, _USER_EMAIL, _USER_PASSWORD)
    _delete_audits(_USER_ID)

    before = client.get(
        f"/user-admin/reset-history/{_USER_ID}", headers=curator_headers
    )
    assert before.get_json()["data"]["lastLogin"] is None

    # log in only after clearing the trail, so the LOGIN audit is the only one
    get_access(
        client,
        email=_USER_EMAIL,
        password=_USER_PASSWORD,
        roles=[Role.PRESCRIPTION_ANALYST.value],
    )

    response = client.get(
        f"/user-admin/reset-history/{_USER_ID}", headers=curator_headers
    )

    assert response.status_code == 200
    assert response.get_json()["data"]["lastLogin"]
    assert _audits(_USER_ID, UserAuditTypeEnum.LOGIN)


def test_reset_history_requires_permission(client, user_manager_headers):
    """GET /user-admin/reset-history - USER_MANAGER is not enough [401 UNAUTHORIZED]"""
    response = client.get(
        f"/user-admin/reset-history/{_USER_ID}", headers=user_manager_headers
    )

    assert response.status_code == 401


def test_reset_history_rejects_unknown_user(client, curator_headers):
    """GET /user-admin/reset-history - unknown user is rejected [400 BAD REQUEST]"""
    response = client.get("/user-admin/reset-history/99999", headers=curator_headers)

    assert response.status_code == 400
    assert response.get_json()["code"] == "errors.businessRules"


def test_send_reset_email_requires_configured_odoo(client, curator_headers):
    """POST /user-admin/send-reset-email - missing ODOO config is refused [400]"""
    _upsert_user(_USER_ID, _USER_EMAIL, _USER_PASSWORD)
    _delete_audits(_USER_ID)

    with mock.patch.object(Config, "ODOO_API_URL", ""):
        response = client.post(
            "/user-admin/send-reset-email",
            headers=curator_headers,
            json={"idUser": _USER_ID},
        )

    assert response.status_code == 400
    assert response.get_json()["code"] == "errors.businessRules"


# --- GET /user/forget: retry delivery -----------------------------------------
# A request made less than one hour after the previous one is treated as "the
# first email never arrived" and goes out through ODOO instead of SMTP. These
# tests live down here because they reuse the _OdooEmailStub defined above.


def _forget_password(client, email: str, stub: _OdooEmailStub):
    """Call /user/forget with the ODOO client mocked out."""
    with (
        mock.patch.object(Config, "ODOO_API_URL", "http://odoo.test/"),
        mock.patch("services.email_service.odoo_client.get_client", return_value=stub),
    ):
        return client.get(f"/user/forget?email={email}")


def test_forget_password_uses_smtp_on_the_first_request(client):
    """GET /user/forget - a first request in the hour does not touch ODOO"""
    _upsert_user(_USER_ID, _USER_EMAIL, _USER_PASSWORD)
    _delete_audits(_USER_ID)
    stub = _OdooEmailStub()

    response = _forget_password(client, _USER_EMAIL, stub)

    assert response.status_code == 200
    assert stub.calls == []


def test_forget_password_retry_within_an_hour_uses_odoo(client):
    """GET /user/forget - the second request in the hour is delivered by ODOO"""
    _upsert_user(_USER_ID, _USER_EMAIL, _USER_PASSWORD)
    _delete_audits(_USER_ID)
    stub = _OdooEmailStub()

    assert _forget_password(client, _USER_EMAIL, stub).status_code == 200
    response = _forget_password(client, _USER_EMAIL, stub)

    assert response.status_code == 200

    audits = _audits(_USER_ID, UserAuditTypeEnum.FORGOT_PASSWORD)
    assert len(audits) == 2

    mail = stub.created_mail()
    assert mail["email_to"] == _USER_EMAIL
    # the retry carries the token audited by the retry, not the first one
    assert audits[1].pw_token in mail["body_html"]
    assert audits[0].pw_token not in mail["body_html"]


def test_forget_password_retry_survives_an_odoo_failure(client):
    """GET /user/forget - a failed ODOO retry still answers 200 and keeps the audit"""
    _upsert_user(_USER_ID, _USER_EMAIL, _USER_PASSWORD)
    _delete_audits(_USER_ID)

    assert _forget_password(client, _USER_EMAIL, _OdooEmailStub()).status_code == 200
    # an unreachable ODOO must not leak a 502: /user/forget answers 200 to
    # everyone, and the audit row holding the token must survive the failure
    with (
        mock.patch.object(Config, "ODOO_API_URL", "http://odoo.test/"),
        mock.patch("services.email_service.odoo_client.get_client", return_value=None),
    ):
        response = client.get(f"/user/forget?email={_USER_EMAIL}")

    assert response.status_code == 200
    audits = _audits(_USER_ID, UserAuditTypeEnum.FORGOT_PASSWORD)
    assert len(audits) == 2
    assert audits[1].pw_token
