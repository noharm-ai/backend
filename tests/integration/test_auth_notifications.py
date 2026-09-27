"""Tests: login notifications (``public.notifica``)

Notifications are the banner the app shows right after login. ``/authenticate``
resolves them through ``notification_repository.get_active_notifications`` and
then drops the ones the caller's roles are not meant to see
(``auth_service._notification_visible``), so the whole feature is only
observable on the login payload.

Four rules make up the selection:

* the current day must fall inside ``[inicio, validade]`` (both ends included);
* the row must target the caller's schema, or no schema at all (a NULL
  ``schema`` is the global notice every tenant gets);
* the user must not have dismissed it — a dismissal is a memory record named
  ``info-alert-<idnotifica>-<iduser>``;
* ``grupo_alvo = 'MANAGERS'`` restricts the notice to the manager roles; any
  other value (including NULL) reaches everybody.

At most 10 rows are read, oldest id first, and the payload is ``None`` rather
than an empty list when nothing is left.
"""

import json

import pytest
from sqlalchemy import text

from security.role import Role
from tests.conftest import get_access, make_headers, session, session_commit

# test-generated notifications use ids >= 100000 (see conftest._cleanup)
BASE_ID = 100000
DEMO_USER_ID = 1

_INSERT = text(
    "INSERT INTO public.notifica "
    "(idnotifica, titulo, tooltip, link, icon, classname, inicio, validade, schema, texto, grupo_alvo) "
    "VALUES (:id, :title, :tooltip, :link, :icon, :classname, "
    "current_date + CAST(:starts_in AS interval), current_date + CAST(:ends_in AS interval), "
    ":schema, :text, :target_group)"
)


def _add_notification(
    id: int,
    schema="demo",
    starts_in=-1,
    ends_in=1,
    target_group=None,
    title="Aviso de teste",
):
    """Insert one notification, its window given in days around today."""
    session.execute(
        _INSERT,
        {
            "id": id,
            "title": title,
            "tooltip": "dica de teste",
            "link": "https://example.com/aviso",
            "icon": "info",
            "classname": "info-alert",
            "starts_in": f"{starts_in} days",
            "ends_in": f"{ends_in} days",
            "schema": schema,
            "text": "corpo do aviso",
            "target_group": target_group,
        },
    )
    session_commit()


def _dismiss(id_notification: int, id_user=DEMO_USER_ID):
    """Write the memory record that marks a notification as read.

    ``public`` is where the query looks for it — see the dismissal tests below
    for the schema the app itself writes to.
    """
    session.execute(
        text(
            "INSERT INTO public.memoria (tipo, valor, update_at, update_by) "
            "VALUES (:kind, CAST('true' AS json), now(), :user)"
        ),
        {"kind": f"info-alert-{id_notification}-{id_user}", "user": id_user},
    )
    session_commit()


def _cleanup():
    session.execute(
        text("DELETE FROM public.notifica WHERE idnotifica >= :base"), {"base": BASE_ID}
    )
    # both schemas: the query reads the dismissal from public, the app writes
    # it to the tenant schema
    session.execute(
        text("DELETE FROM public.memoria WHERE tipo LIKE 'info-alert-1000%'")
    )
    session.execute(text("DELETE FROM demo.memoria WHERE tipo LIKE 'info-alert-1000%'"))
    session_commit()


@pytest.fixture(autouse=True)
def clean_notifications():
    """No test may see a notification another one left behind."""
    _cleanup()
    yield
    _cleanup()


def _login(client, roles=None):
    """Authenticate as the demo user and return the login payload."""
    roles = roles or [Role.PRESCRIPTION_ANALYST.value]
    # get_access writes the roles on the user before authenticating
    get_access(client, roles=roles)

    response = client.post(
        "/authenticate",
        data=json.dumps({"email": "demo", "password": "demo"}),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )

    assert response.status_code == 200

    return response.get_json()


def _notification_ids(client, roles=None):
    return [n["id"] for n in (_login(client, roles).get("notifications") or [])]


# ---------------------------------------------------------------------------
# selection
# ---------------------------------------------------------------------------


def test_login_without_notifications_reports_none(client):
    """The key is present and null — not an empty list — when nothing applies"""
    assert _login(client).get("notifications") is None


def test_active_notification_of_the_schema_is_returned(client):
    _add_notification(BASE_ID + 1)

    assert _notification_ids(client) == [BASE_ID + 1]


def test_notification_of_another_schema_is_not_returned(client):
    """Each tenant only sees what was addressed to it"""
    _add_notification(BASE_ID + 2, schema="outro_schema")

    assert _notification_ids(client) == []


def test_notification_without_schema_reaches_every_tenant(client):
    """A NULL schema is the global notice"""
    _add_notification(BASE_ID + 3, schema=None)

    assert _notification_ids(client) == [BASE_ID + 3]


def test_notification_that_has_not_started_is_not_returned(client):
    _add_notification(BASE_ID + 4, starts_in=1, ends_in=5)

    assert _notification_ids(client) == []


def test_expired_notification_is_not_returned(client):
    _add_notification(BASE_ID + 5, starts_in=-5, ends_in=-1)

    assert _notification_ids(client) == []


def test_window_includes_both_ends(client):
    """A notification that starts and ends today is shown today"""
    _add_notification(BASE_ID + 6, starts_in=0, ends_in=0)

    assert _notification_ids(client) == [BASE_ID + 6]


def test_notifications_come_oldest_first(client):
    _add_notification(BASE_ID + 9)
    _add_notification(BASE_ID + 7)
    _add_notification(BASE_ID + 8)

    assert _notification_ids(client) == [BASE_ID + 7, BASE_ID + 8, BASE_ID + 9]


def test_at_most_ten_notifications_are_read(client):
    """The banner is capped, so the oldest ten win"""
    for i in range(12):
        _add_notification(BASE_ID + 20 + i)

    assert _notification_ids(client) == [BASE_ID + 20 + i for i in range(10)]


# ---------------------------------------------------------------------------
# payload
# ---------------------------------------------------------------------------


def test_notification_payload_carries_every_field(client):
    _add_notification(BASE_ID + 11, starts_in=0, ends_in=3, title="Manutenção")

    notification = _login(client)["notifications"][0]
    today = session.execute(text("SELECT current_date")).scalar()

    assert notification == {
        "id": BASE_ID + 11,
        "title": "Manutenção",
        "tooltip": "dica de teste",
        "link": "https://example.com/aviso",
        "icon": "info",
        "classname": "info-alert",
        "text": "corpo do aviso",
        "target_group": None,
        "date": today.isoformat(),
    }


# ---------------------------------------------------------------------------
# target group
# ---------------------------------------------------------------------------


def test_managers_notification_is_hidden_from_other_roles(client):
    _add_notification(BASE_ID + 12, target_group="MANAGERS")

    assert _notification_ids(client, roles=[Role.PRESCRIPTION_ANALYST.value]) == []


@pytest.mark.parametrize(
    "role",
    [
        Role.USER_MANAGER.value,
        Role.CONFIG_MANAGER.value,
        Role.SUPPORT_MANAGER.value,
    ],
)
def test_managers_notification_reaches_each_manager_role(client, role):
    _add_notification(BASE_ID + 13, target_group="MANAGERS")

    assert _notification_ids(client, roles=[role]) == [BASE_ID + 13]


def test_target_group_is_matched_case_insensitively(client):
    """The stored value is upper-cased before the comparison"""
    _add_notification(BASE_ID + 14, target_group="managers")

    assert _notification_ids(client, roles=[Role.PRESCRIPTION_ANALYST.value]) == []
    assert _notification_ids(client, roles=[Role.USER_MANAGER.value]) == [BASE_ID + 14]


@pytest.mark.parametrize("target_group", [None, "ALL", "EVERYONE"])
def test_any_other_target_group_reaches_everybody(client, target_group):
    """Only MANAGERS restricts the audience; anything else is treated as ALL"""
    _add_notification(BASE_ID + 15, target_group=target_group)

    assert _notification_ids(client, roles=[Role.PRESCRIPTION_ANALYST.value]) == [
        BASE_ID + 15
    ]


# ---------------------------------------------------------------------------
# dismissal
# ---------------------------------------------------------------------------


def test_dismissed_notification_is_not_returned_again(client):
    _add_notification(BASE_ID + 16)
    _dismiss(BASE_ID + 16)

    assert _notification_ids(client) == []


def test_dismissal_belongs_to_the_user_who_wrote_it(client):
    """Another user's dismissal does not hide the notification from this one"""
    _add_notification(BASE_ID + 17)
    _dismiss(BASE_ID + 17, id_user=DEMO_USER_ID + 1)

    assert _notification_ids(client) == [BASE_ID + 17]


def test_dismissal_only_hides_the_notification_it_names(client):
    _add_notification(BASE_ID + 18)
    _add_notification(BASE_ID + 19)
    _dismiss(BASE_ID + 18)

    assert _notification_ids(client) == [BASE_ID + 19]


def test_dismissal_saved_by_the_app_does_not_hide_the_notification(client):
    """BUG (pinned): the app saves the dismissal where the query never looks.

    The banner's "read" action goes through ``PUT /memory``, which writes to the
    *tenant* schema like every other memory record. ``get_active_notifications``
    runs on the request-wide session, whose ``schema_translate_map`` still
    points at ``public`` during ``/authenticate``, so the subquery only ever
    finds a dismissal stored in ``public.memoria`` — the one written above,
    which no code path produces.

    The user therefore keeps seeing the same notification on every login. This
    test records what ships today; fixing the schema mismatch is what should
    make it fail.
    """
    _add_notification(BASE_ID + 10)
    headers = make_headers(get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value]))

    saved = client.put(
        "/memory",
        data=json.dumps(
            {"type": f"info-alert-{BASE_ID + 10}-{DEMO_USER_ID}", "value": True}
        ),
        headers=headers,
    )
    assert saved.status_code == 200

    stored_in = session.execute(
        text("SELECT count(*) FROM demo.memoria WHERE tipo = :kind"),
        {"kind": f"info-alert-{BASE_ID + 10}-{DEMO_USER_ID}"},
    ).scalar()
    assert stored_in == 1, "the app stores the dismissal on the tenant schema"

    assert _notification_ids(client) == [BASE_ID + 10]
