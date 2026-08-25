"""Integration tests for the support ticket listing endpoints.

Three read-only endpoints back the support inbox:

* ``/support/list-tickets/v2`` — the caller's own tickets, the ones they merely
  follow, and (for ADMIN_SUPPORT holders) every ticket of their organization.
* ``/support/list-pending`` — the subset waiting on the caller's answer.
* ``/support/list-requesters`` — who in the caller's schema may open a ticket.

The first two read from Odoo over XML-RPC, which is unreachable from a test, so
``support_service._get_client`` is replaced by a stub that records the queries it
is given and answers from a canned ticket set. That makes two things assertable
that matter in production: the *filters* sent to Odoo (a wrong domain leaks
another organization's tickets) and the degraded behaviour when Odoo times out —
the client is ``None`` then, and the inbox must come back empty instead of 500.

``list-requesters`` reads public.usuario instead, so it gets real rows: users of
the caller's schema, of another schema, inactive, and without a support role.
"""

import json

import pytest
from sqlalchemy import text

from security.role import Role
from services import support_service
from tests.conftest import get_access, make_headers, session, session_commit
from utils import status

LIST_URL = "/support/list-tickets/v2"
PENDING_URL = "/support/list-pending"
REQUESTERS_URL = "/support/list-requesters"

# the demo user the tests authenticate as
DEMO_USER_ID = 1
DEMO_EMAIL = "demo"
DEMO_SCHEMA = "demo"

# every public.usuario row created here uses this email prefix
_EMAIL_PREFIX = "zztest_supl_"

# a schema no seed user belongs to, used for the cross-schema cases
_OTHER_SCHEMA = "zztest_supl_other"

# Odoo ids for the canned tickets
_OWN_TICKET = 101
_FOLLOWED_TICKET = 102
_ORG_TICKET = 103
_PENDING_TICKET = 104

# hard-coded in list_pending_action
_STAGE_WAITING_RESPONSE = 3
_TAG_NO_RESPONSE = 23

# hard-coded in list_tickets_v2
_IGNORED_TAGS = [46, 48, 58, 60]


class OdooStub:
    """A stand-in Odoo client that records every query and answers from a script.

    ``support_service`` calls the object returned by ``_get_client`` as
    ``client(model=..., action=..., payload=..., options=...)``, so the stub is
    callable. ``partner`` decides whether the caller is a known res.partner and
    the ticket lists are returned in the order the service asks for them.
    """

    def __init__(self, partner=None, tickets=None):
        self.partner = partner if partner is not None else []
        self.tickets = tickets or {}
        self.calls = []

    def __call__(self, model, action, payload, options):
        self.calls.append(
            {"model": model, "action": action, "payload": payload, "options": options}
        )

        if model == "res.partner":
            return self.partner

        # the ticket queries are told apart by the fields their domain filters on
        domain = payload[0]
        keys = [condition[0] for condition in domain]

        if "message_partner_ids" in keys:
            return self.tickets.get("following", [])

        if "x_studio_schema_1" in keys:
            return self.tickets.get("organization", [])

        return self.tickets.get("mine", [])

    def ticket_query(self, field):
        """The recorded helpdesk.ticket query whose domain filters on ``field``"""
        for call in self.calls:
            if call["model"] != "helpdesk.ticket":
                continue
            if any(condition[0] == field for condition in call["payload"][0]):
                return call
        return None


def _ticket(ticket_id: int, name: str = "Chamado"):
    """The shape list_tickets_v2 passes through untouched"""
    return {"id": ticket_id, "name": name, "access_token": f"tok-{ticket_id}"}


def _install(monkeypatch, stub):
    """Point the service at a stub instead of the real Odoo transport"""
    monkeypatch.setattr(support_service, "_get_client", lambda: stub)
    return stub


def _headers(client, roles):
    return make_headers(get_access(client, roles=roles))


def _data(response):
    assert response.status_code == status.HTTP_200_OK
    return json.loads(response.data)["data"]


# SUPPORT_REQUESTER can read tickets but holds no ADMIN_SUPPORT: the plain user.
REQUESTER_ROLES = [Role.SUPPORT_REQUESTER.value]
# SUPPORT_MANAGER is the realistic ADMIN_SUPPORT holder.
MANAGER_ROLES = [Role.SUPPORT_MANAGER.value]


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _cleanup():
    """Remove every reserved row these tests may have created"""
    session.execute(
        text("DELETE FROM public.usuario WHERE email LIKE :prefix"),
        {"prefix": f"{_EMAIL_PREFIX}%"},
    )
    # the seed data has no usuario_extra row for the demo user, so the tests own it
    session.execute(
        text("DELETE FROM public.usuario_extra WHERE idusuario = :uid"),
        {"uid": DEMO_USER_ID},
    )
    session_commit()


@pytest.fixture(autouse=True)
def clean_support_rows():
    _cleanup()
    yield
    _cleanup()


@pytest.fixture
def extra_schemas():
    """Give the demo user two extra organization schemas, as UserExtra does"""

    def _add(schemas):
        session.execute(
            text(
                "INSERT INTO public.usuario_extra "
                "(idusuario, config, created_at, created_by) "
                "VALUES (:uid, CAST(:config AS json), now(), :uid)"
            ),
            {
                "uid": DEMO_USER_ID,
                "config": json.dumps({"schemas": [{"name": name} for name in schemas]}),
            },
        )
        session_commit()

    return _add


def _add_user(name: str, suffix: str, roles: list, schema=DEMO_SCHEMA, active=True):
    """Insert a public.usuario row with the reserved email prefix"""
    session.execute(
        text(
            "INSERT INTO public.usuario (nome, email, senha, schema, config, ativo) "
            "VALUES (:name, :email, 'x', :schema, CAST(:config AS json), :active)"
        ),
        {
            "name": name,
            "email": f"{_EMAIL_PREFIX}{suffix}@noharm.ai",
            "schema": schema,
            "config": json.dumps({"roles": roles}),
            "active": active,
        },
    )
    session_commit()


# ---------------------------------------------------------------------------
# list-tickets/v2: Odoo unreachable
# ---------------------------------------------------------------------------


def test_list_tickets_returns_empty_lists_when_odoo_is_unreachable(client, monkeypatch):
    """An Odoo timeout leaves _get_client returning None: the inbox degrades to
    empty rather than failing the whole page"""
    monkeypatch.setattr(support_service, "_get_client", lambda: None)
    headers = _headers(client, REQUESTER_ROLES)

    data = _data(client.get(LIST_URL, headers=headers))

    assert data == {"myTickets": [], "following": [], "organization": []}


def test_list_pending_returns_an_empty_list_when_odoo_is_unreachable(
    client, monkeypatch
):
    """Same fallback for the pending-action badge"""
    monkeypatch.setattr(support_service, "_get_client", lambda: None)
    headers = _headers(client, REQUESTER_ROLES)

    assert _data(client.get(PENDING_URL, headers=headers)) == []


# ---------------------------------------------------------------------------
# list-tickets/v2: the caller resolved as a res.partner
# ---------------------------------------------------------------------------


def test_list_tickets_looks_the_caller_up_by_their_own_email(client, monkeypatch):
    """The partner lookup keys on the stored email, not on the JWT identity"""
    stub = _install(monkeypatch, OdooStub(partner=[{"id": 7}]))
    headers = _headers(client, REQUESTER_ROLES)

    client.get(LIST_URL, headers=headers)

    partner_call = stub.calls[0]
    assert partner_call["model"] == "res.partner"
    assert partner_call["payload"] == [[["email", "=", DEMO_EMAIL]]]


def test_list_tickets_queries_own_tickets_by_partner_id(client, monkeypatch):
    """With a known partner the caller's tickets are the ones they own"""
    stub = _install(
        monkeypatch,
        OdooStub(
            partner=[{"id": 7}, {"id": 8}], tickets={"mine": [_ticket(_OWN_TICKET)]}
        ),
    )
    headers = _headers(client, REQUESTER_ROLES)

    data = _data(client.get(LIST_URL, headers=headers))

    assert [t["id"] for t in data["myTickets"]] == [_OWN_TICKET]
    assert stub.ticket_query("partner_id")["payload"] == [
        [["partner_id", "in", [7, 8]]]
    ]


def test_list_tickets_separates_followed_tickets_from_owned_ones(client, monkeypatch):
    """A ticket the caller follows but does not own belongs under "following" """
    _install(
        monkeypatch,
        OdooStub(
            partner=[{"id": 7}],
            tickets={
                "mine": [_ticket(_OWN_TICKET)],
                "following": [_ticket(_FOLLOWED_TICKET)],
            },
        ),
    )
    headers = _headers(client, REQUESTER_ROLES)

    data = _data(client.get(LIST_URL, headers=headers))

    assert [t["id"] for t in data["myTickets"]] == [_OWN_TICKET]
    assert [t["id"] for t in data["following"]] == [_FOLLOWED_TICKET]


def test_list_tickets_does_not_repeat_an_owned_ticket_under_following(
    client, monkeypatch
):
    """Odoo lists the author among the followers, so the owned ticket comes back
    in both queries and must be shown only once"""
    stub = _install(
        monkeypatch,
        OdooStub(
            partner=[{"id": 7}],
            tickets={
                "mine": [_ticket(_OWN_TICKET)],
                "following": [_ticket(_OWN_TICKET), _ticket(_FOLLOWED_TICKET)],
            },
        ),
    )
    headers = _headers(client, REQUESTER_ROLES)

    data = _data(client.get(LIST_URL, headers=headers))

    assert [t["id"] for t in data["following"]] == [_FOLLOWED_TICKET]
    assert stub.ticket_query("message_partner_ids") is not None


def test_list_tickets_falls_back_to_the_email_when_no_partner_exists(
    client, monkeypatch
):
    """A user who never had a res.partner created still sees the tickets opened
    with their email address"""
    stub = _install(
        monkeypatch, OdooStub(partner=[], tickets={"mine": [_ticket(_OWN_TICKET)]})
    )
    headers = _headers(client, REQUESTER_ROLES)

    data = _data(client.get(LIST_URL, headers=headers))

    assert [t["id"] for t in data["myTickets"]] == [_OWN_TICKET]
    assert stub.ticket_query("partner_email")["payload"] == [
        [["partner_email", "=", DEMO_EMAIL]]
    ]
    # without a partner id there is nothing to resolve "following" against
    assert data["following"] == []
    assert stub.ticket_query("message_partner_ids") is None


def test_list_tickets_normalizes_a_falsy_odoo_answer(client, monkeypatch):
    """Odoo answers False rather than [] when a search matches nothing; the
    response contract is still three lists"""
    stub = OdooStub(partner=[{"id": 7}])
    stub.tickets = {"mine": False, "following": False}
    _install(monkeypatch, stub)
    headers = _headers(client, REQUESTER_ROLES)

    data = _data(client.get(LIST_URL, headers=headers))

    assert data == {"myTickets": [], "following": [], "organization": []}


def test_list_tickets_survives_a_falsy_answer_to_only_one_query(client, monkeypatch):
    """The dedup between owned and followed tickets runs over both answers, so
    either one coming back False must not take the request down"""
    stub = OdooStub(partner=[{"id": 7}])
    stub.tickets = {"mine": [_ticket(_OWN_TICKET)], "following": False}
    _install(monkeypatch, stub)
    headers = _headers(client, REQUESTER_ROLES)

    data = _data(client.get(LIST_URL, headers=headers))

    assert [t["id"] for t in data["myTickets"]] == [_OWN_TICKET]
    assert data["following"] == []


def test_list_tickets_keeps_followed_tickets_when_the_caller_owns_none(
    client, monkeypatch
):
    """The mirror case: nothing owned, something followed"""
    stub = OdooStub(partner=[{"id": 7}])
    stub.tickets = {"mine": False, "following": [_ticket(_FOLLOWED_TICKET)]}
    _install(monkeypatch, stub)
    headers = _headers(client, REQUESTER_ROLES)

    data = _data(client.get(LIST_URL, headers=headers))

    assert data["myTickets"] == []
    assert [t["id"] for t in data["following"]] == [_FOLLOWED_TICKET]


def test_list_tickets_asks_odoo_for_the_fields_the_inbox_renders(client, monkeypatch):
    """The ticket queries are bounded and ordered, and carry the reference the
    inbox links to"""
    stub = _install(monkeypatch, OdooStub(partner=[{"id": 7}]))
    headers = _headers(client, REQUESTER_ROLES)

    client.get(LIST_URL, headers=headers)

    options = stub.ticket_query("partner_id")["options"]
    assert options["limit"] == 50
    assert options["order"] == "create_date desc"
    assert "ticket_ref" in options["fields"]
    assert "access_token" in options["fields"]


# ---------------------------------------------------------------------------
# list-tickets/v2: the organization list is gated by ADMIN_SUPPORT
# ---------------------------------------------------------------------------


def test_organization_tickets_stay_empty_without_admin_support(client, monkeypatch):
    """A plain requester never sees their organization's tickets, and the query
    is not even sent"""
    stub = _install(
        monkeypatch,
        OdooStub(partner=[{"id": 7}], tickets={"organization": [_ticket(_ORG_TICKET)]}),
    )
    headers = _headers(client, REQUESTER_ROLES)

    data = _data(client.get(LIST_URL, headers=headers))

    assert data["organization"] == []
    assert stub.ticket_query("x_studio_schema_1") is None


def test_admin_support_sees_the_tickets_of_their_own_schema(client, monkeypatch):
    """ADMIN_SUPPORT widens the inbox to the caller's schema"""
    stub = _install(
        monkeypatch,
        OdooStub(partner=[{"id": 7}], tickets={"organization": [_ticket(_ORG_TICKET)]}),
    )
    headers = _headers(client, MANAGER_ROLES)

    data = _data(client.get(LIST_URL, headers=headers))

    assert [t["id"] for t in data["organization"]] == [_ORG_TICKET]

    domain = stub.ticket_query("x_studio_schema_1")["payload"][0]
    schema_condition = next(c for c in domain if c[0] == "x_studio_schema_1")
    assert schema_condition == ["x_studio_schema_1", "in", [DEMO_SCHEMA]]


def test_admin_support_also_sees_the_schemas_granted_out_of_band(
    client, monkeypatch, extra_schemas
):
    """A support manager of several hospitals has the extra schemas in UserExtra,
    and all of them must be part of the organization query"""
    extra_schemas([_OTHER_SCHEMA, "zztest_supl_third"])
    stub = _install(monkeypatch, OdooStub(partner=[{"id": 7}]))
    headers = _headers(client, MANAGER_ROLES)

    client.get(LIST_URL, headers=headers)

    domain = stub.ticket_query("x_studio_schema_1")["payload"][0]
    schema_condition = next(c for c in domain if c[0] == "x_studio_schema_1")
    assert schema_condition[2] == [DEMO_SCHEMA, _OTHER_SCHEMA, "zztest_supl_third"]


def test_extra_schemas_without_a_name_are_skipped(client, monkeypatch):
    """A malformed UserExtra entry must not put a null into the Odoo domain"""
    session.execute(
        text(
            "INSERT INTO public.usuario_extra "
            "(idusuario, config, created_at, created_by) "
            "VALUES (:uid, CAST(:config AS json), now(), :uid)"
        ),
        {
            "uid": DEMO_USER_ID,
            "config": json.dumps(
                {"schemas": [{"friendlyName": "Sem nome"}, {"name": _OTHER_SCHEMA}]}
            ),
        },
    )
    session_commit()
    stub = _install(monkeypatch, OdooStub(partner=[{"id": 7}]))
    headers = _headers(client, MANAGER_ROLES)

    client.get(LIST_URL, headers=headers)

    domain = stub.ticket_query("x_studio_schema_1")["payload"][0]
    schema_condition = next(c for c in domain if c[0] == "x_studio_schema_1")
    assert schema_condition[2] == [DEMO_SCHEMA, _OTHER_SCHEMA]


def test_organization_query_excludes_the_internal_tags(client, monkeypatch):
    """Internal NoHarm tickets are tagged and must stay out of the customer view"""
    stub = _install(monkeypatch, OdooStub(partner=[{"id": 7}]))
    headers = _headers(client, MANAGER_ROLES)

    client.get(LIST_URL, headers=headers)

    domain = stub.ticket_query("x_studio_schema_1")["payload"][0]

    assert ["tag_ids", "not in", _IGNORED_TAGS] in domain


def test_admin_support_without_extra_config_still_gets_its_own_schema(
    client, monkeypatch
):
    """No UserExtra row at all is the common case and must not break the query"""
    stub = _install(monkeypatch, OdooStub(partner=[{"id": 7}]))
    headers = _headers(client, MANAGER_ROLES)

    client.get(LIST_URL, headers=headers)

    domain = stub.ticket_query("x_studio_schema_1")["payload"][0]
    schema_condition = next(c for c in domain if c[0] == "x_studio_schema_1")
    assert schema_condition[2] == [DEMO_SCHEMA]


# ---------------------------------------------------------------------------
# list-pending
# ---------------------------------------------------------------------------


def test_list_pending_returns_the_tickets_waiting_on_the_caller(client, monkeypatch):
    """The badge counts tickets in the waiting stage carrying the no-response tag"""
    stub = _install(
        monkeypatch,
        OdooStub(partner=[{"id": 7}], tickets={"mine": [_ticket(_PENDING_TICKET)]}),
    )
    headers = _headers(client, REQUESTER_ROLES)

    data = _data(client.get(PENDING_URL, headers=headers))

    assert [t["id"] for t in data] == [_PENDING_TICKET]

    domain = stub.ticket_query("partner_id")["payload"][0]
    assert ["partner_id", "in", [7]] in domain
    assert ["stage_id", "in", [_STAGE_WAITING_RESPONSE]] in domain
    assert ["tag_ids", "in", [_TAG_NO_RESPONSE]] in domain


def test_list_pending_normalizes_a_falsy_odoo_answer(client, monkeypatch):
    """Nothing pending comes back from Odoo as False; the endpoint still answers
    a list, because the badge counts its length"""
    stub = OdooStub(partner=[{"id": 7}])
    stub.tickets = {"mine": False}
    _install(monkeypatch, stub)
    headers = _headers(client, REQUESTER_ROLES)

    assert _data(client.get(PENDING_URL, headers=headers)) == []


def test_list_pending_is_empty_when_the_caller_has_no_partner(client, monkeypatch):
    """Without a res.partner there is no ticket owner to filter on, so the
    pending list stays empty and Odoo is not asked for tickets at all"""
    stub = _install(
        monkeypatch, OdooStub(partner=[], tickets={"mine": [_ticket(_PENDING_TICKET)]})
    )
    headers = _headers(client, REQUESTER_ROLES)

    assert _data(client.get(PENDING_URL, headers=headers)) == []
    assert stub.ticket_query("partner_id") is None


# ---------------------------------------------------------------------------
# list-requesters
# ---------------------------------------------------------------------------


def _requester_emails(client, headers):
    data = _data(client.get(REQUESTERS_URL, headers=headers))
    return [r["email"] for r in data["requesters"]]


def test_list_requesters_returns_both_support_roles(client):
    """Whoever may open a ticket is listed: requesters and managers alike"""
    _add_user("ZZTEST A Requester", "req", [Role.SUPPORT_REQUESTER.value])
    _add_user("ZZTEST B Manager", "man", [Role.SUPPORT_MANAGER.value])
    headers = _headers(client, MANAGER_ROLES)

    emails = _requester_emails(client, headers)

    assert f"{_EMAIL_PREFIX}req@noharm.ai" in emails
    assert f"{_EMAIL_PREFIX}man@noharm.ai" in emails


def test_list_requesters_omits_users_without_a_support_role(client):
    """A role that cannot open a ticket has no place in the requester picker"""
    _add_user("ZZTEST C Viewer", "viewer", [Role.VIEWER.value])
    headers = _headers(client, MANAGER_ROLES)

    assert f"{_EMAIL_PREFIX}viewer@noharm.ai" not in _requester_emails(client, headers)


def test_list_requesters_omits_deactivated_users(client):
    """A deactivated account keeps its role but must not be offered"""
    _add_user(
        "ZZTEST D Inactive", "inactive", [Role.SUPPORT_REQUESTER.value], active=False
    )
    headers = _headers(client, MANAGER_ROLES)

    assert f"{_EMAIL_PREFIX}inactive@noharm.ai" not in _requester_emails(
        client, headers
    )


def test_list_requesters_is_scoped_to_the_callers_schema(client):
    """A support requester of another hospital is none of this caller's business"""
    _add_user(
        "ZZTEST E Other",
        "other",
        [Role.SUPPORT_REQUESTER.value],
        schema=_OTHER_SCHEMA,
    )
    headers = _headers(client, MANAGER_ROLES)

    assert f"{_EMAIL_PREFIX}other@noharm.ai" not in _requester_emails(client, headers)


def test_list_requesters_exposes_only_the_name_and_email(client):
    """The picker needs a label and an address, and nothing else leaks"""
    _add_user("ZZTEST A Requester", "req", [Role.SUPPORT_REQUESTER.value])
    headers = _headers(client, MANAGER_ROLES)

    data = _data(client.get(REQUESTERS_URL, headers=headers))
    entry = next(
        r for r in data["requesters"] if r["email"] == f"{_EMAIL_PREFIX}req@noharm.ai"
    )

    assert entry == {
        "name": "ZZTEST A Requester",
        "email": f"{_EMAIL_PREFIX}req@noharm.ai",
    }


def test_list_requesters_is_ordered_by_name(client):
    """The picker is alphabetical, so the query must order by name"""
    _add_user("ZZTEST Zeta", "zeta", [Role.SUPPORT_REQUESTER.value])
    _add_user("ZZTEST Alpha", "alpha", [Role.SUPPORT_REQUESTER.value])
    headers = _headers(client, MANAGER_ROLES)

    data = _data(client.get(REQUESTERS_URL, headers=headers))
    names = [r["name"] for r in data["requesters"] if r["name"].startswith("ZZTEST")]

    assert names == sorted(names)


# ---------------------------------------------------------------------------
# permissions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("url", [LIST_URL, PENDING_URL, REQUESTERS_URL])
def test_support_listing_requires_read_support(client, url):
    """READ_SUPPORT is broadly granted (VIEWER holds it), so the refusal is shown
    with STATIC_USER — the integration role that has no business in the inbox"""
    headers = _headers(client, [Role.STATIC_USER.value])

    assert client.get(url, headers=headers).status_code == (
        status.HTTP_401_UNAUTHORIZED
    )
