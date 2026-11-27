"""Integration tests for the public getname validation page endpoints
(``/public/getname-validation/<token>``, docs/agents/getname-validation.md).

The link is a row the admin project writes in ``public.schema_config_audit``:
the ``_create_link`` helper writes it the same way. The helpdesk is the only
outbound boundary and it is patched in every test that saves a result, so no
test reaches ODOO. Every row written here is removed by the ``getname_setup``
fixture, which also restores the schema's getname settings.
"""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import jwt
import pytest
from sqlalchemy import text

from models.enums import SchemaConfigAuditTypeEnum
from services import getname_validation_service
from tests.conftest import session, session_commit

AUDIT_TYPE = SchemaConfigAuditTypeEnum.GETNAME_VALIDATION.value
# invented for this file, never a real credential
GETNAME_SECRET = "zztest-getname-secret-0123456789abcdef"  # gitleaks:allow
LINK_SECRET = "0123456789abcdef0123456789abcdef0123456789abcdef"  # gitleaks:allow
# example.org is reserved for documentation: no client host in a test
NAME_URL = "https://getname.example.org/patient-name/{idPatient}"
MULTIPLE_URL = "https://getname.example.org/patient-name/multiple"
CREATED_BY = 1

PASSED_RESULT = {
    "status": "passed",
    "diagnosis": "ok",
    "checks": [
        {"id": "reachability", "status": "passed", "httpStatus": 200, "durationMs": 42},
        {"id": "database", "status": "passed", "code": "healthy", "durationMs": 12},
    ],
    "environment": {
        "userAgent": "Mozilla/5.0 (test)",
        "browser": "Google Chrome 142.0.7444.60",
        "platform": "Windows 11",
        "pageOrigin": "https://app.example.com",
        "online": True,
        "targetAddressSpace": "hostname",
        "permissions": {"local-network-access": "granted"},
        "getnameVersion": "3.0.0",
    },
}


def _clean_rows():
    """Remove every link and result of the validation"""
    session.execute(
        text("DELETE FROM public.schema_config_audit WHERE tp_audit = :type"),
        {"type": AUDIT_TYPE},
    )


def _set_getname(config: dict | None, memory: dict | None):
    """Write the getname settings of the demo schema: the config block and the
    urls the app calls (memoria `getnameurl`); None removes each"""
    session.execute(
        text(
            "UPDATE public.schema_config SET configuracao = CAST(:config AS jsonb) "
            "WHERE schema_name = 'demo'"
        ),
        {"config": json.dumps({"getname": config}) if config is not None else None},
    )
    session.execute(text("DELETE FROM demo.memoria WHERE tipo = 'getnameurl'"))
    if memory is not None:
        session.execute(
            text(
                "INSERT INTO demo.memoria (tipo, valor, update_at, update_by) "
                "VALUES ('getnameurl', CAST(:value AS json), now(), 0)"
            ),
            {"value": json.dumps(memory)},
        )
    session_commit()


@pytest.fixture
def getname_setup():
    """A getname of type default reached by the browser; restores everything"""
    original = session.execute(
        text(
            "SELECT CAST(configuracao AS text) FROM public.schema_config "
            "WHERE schema_name = 'demo'"
        )
    ).scalar()
    _clean_rows()
    _set_getname(
        config={"type": "default"},
        memory={"value": NAME_URL, "multiple": MULTIPLE_URL},
    )

    yield

    _clean_rows()
    session.execute(text("DELETE FROM demo.memoria WHERE tipo = 'getnameurl'"))
    session.execute(
        text(
            "UPDATE public.schema_config SET configuracao = CAST(:config AS jsonb) "
            "WHERE schema_name = 'demo'"
        ),
        {"config": original},
    )
    session_commit()


def _create_link(
    expires_in: timedelta = timedelta(days=7), secret: str = LINK_SECRET
) -> str:
    """Write a link row as the admin project does and return its token"""
    expires_at = datetime.now(tz=timezone.utc) + expires_in
    id_link = session.execute(
        text(
            "INSERT INTO public.schema_config_audit "
            "(schema_name, tp_audit, extra, created_at, created_by) "
            "VALUES ('demo', :type, CAST(:extra AS json), now(), :created_by) "
            "RETURNING idschema_config_audit"
        ),
        {
            "type": AUDIT_TYPE,
            "created_by": CREATED_BY,
            "extra": json.dumps(
                {
                    "action": "create_validation_link",
                    "token_hash": hashlib.sha256(secret.encode()).hexdigest(),
                    "expires_at": expires_at.isoformat(),
                }
            ),
        },
    ).scalar()
    session_commit()

    return f"{id_link}-{secret}"


def _results() -> list[dict]:
    """The result rows saved, oldest first"""
    rows = session.execute(
        text(
            "SELECT extra, created_by, schema_name FROM public.schema_config_audit "
            "WHERE tp_audit = :type AND extra ->> 'action' = 'validation_result' "
            "ORDER BY idschema_config_audit"
        ),
        {"type": AUDIT_TYPE},
    ).all()
    session_commit()

    return [
        {"extra": row[0], "created_by": row[1], "schema": row[2]} for row in rows
    ]


def _is_search_by_link(payload) -> bool:
    """Whether a helpdesk search is the one that looks for the ticket of a link
    (by the marker in its title), not the one that reads a ticket by id"""
    return any(condition[0] == "name" for condition in payload[0])


def _odoo(ticket_id: int = 4321, ticket_ref: str = "T4321", existing: bool = False):
    """A helpdesk that accepts everything, and the client to assert on.
    ``existing``: it already holds a ticket of the link that no row recorded."""
    client = MagicMock()

    def execute(model, action, payload, options):  # noqa: ARG001
        """Answer one helpdesk call"""
        if model == "res.partner":
            return []
        if model == "helpdesk.ticket" and action == "web_save":
            return [{"id": ticket_id}]
        if model == "helpdesk.ticket" and action == "search_read":
            if _is_search_by_link(payload) and not existing:
                return []
            return [{"id": ticket_id, "ticket_ref": ticket_ref}]
        return True

    client.side_effect = execute

    return client


def _calls(client, model: str, action: str) -> list:
    """The helpdesk calls of one kind"""
    return [
        call
        for call in client.call_args_list
        if call.kwargs["model"] == model and call.kwargs["action"] == action
    ]


# TEST-NET-3 (RFC 5737): an address reserved for documentation
CLIENT_IP = "203.0.113.7"


def _post_result(
    client, token: str, payload: dict = None, odoo=None, remote_addr: str = CLIENT_IP
):
    """Post a run with the helpdesk patched, as coming from an address"""
    with patch.object(
        getname_validation_service.odoo_client, "get_client", return_value=odoo
    ):
        return client.post(
            f"/public/getname-validation/{token}/result",
            json=PASSED_RESULT if payload is None else payload,
            environ_base={"REMOTE_ADDR": remote_addr},
        )


# --- the link ---------------------------------------------------------------


def test_link_needs_no_authentication(client, getname_setup):
    """The whole point: no headers at all, and it says what to test."""
    token = _create_link()

    response = client.get(f"/public/getname-validation/{token}")

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["valid"] is True
    assert data["schema"] == "demo"
    assert data["mode"] == "browser"
    assert data["getnameType"] == "default"
    assert data["baseUrl"] == "https://getname.example.org/"
    assert data["nameUrl"] == NAME_URL
    assert data["lookup"] == "open"
    assert data["customHeaders"] is False
    assert data["runs"] == 0
    assert data["maxRuns"] == getname_validation_service.MAX_RUNS


@pytest.mark.parametrize(
    "token",
    [
        "abc",
        "1",
        "1-",
        "-" + LINK_SECRET,
        "999999999-" + LINK_SECRET,
        "99999999999999999999999-" + LINK_SECRET,
        # digits for isdigit() that int() refuses, and ones it accepts
        "²-" + LINK_SECRET,
        "٣-" + LINK_SECRET,
    ],
)
def test_unknown_or_malformed_token_is_not_valid(client, getname_setup, token):
    """One answer for junk and for a well formed token that opens nothing."""
    response = client.get(f"/public/getname-validation/{token}")

    assert response.status_code == 200
    assert response.get_json()["data"] == {"valid": False, "reason": None}


def test_wrong_secret_is_not_valid(client, getname_setup):
    """The id alone opens nothing: it is a sequence anyone can count."""
    id_link = _create_link().split("-")[0]

    data = client.get(f"/public/getname-validation/{id_link}-{'f' * 48}").get_json()

    assert data["data"] == {"valid": False, "reason": None}


def test_other_audit_rows_are_not_links(client, getname_setup):
    """A result row (same audit type) never works as a link."""
    token = _create_link()
    _post_result(client, token, odoo=None)
    id_result = session.execute(
        text(
            "SELECT max(idschema_config_audit) FROM public.schema_config_audit "
            "WHERE tp_audit = :type"
        ),
        {"type": AUDIT_TYPE},
    ).scalar()
    session_commit()

    data = client.get(f"/public/getname-validation/{id_result}-{LINK_SECRET}")

    assert data.get_json()["data"]["valid"] is False


def test_expired_link_says_so(client, getname_setup):
    """Who holds the right secret learns the link expired, to ask for another."""
    token = _create_link(expires_in=timedelta(minutes=-1))

    data = client.get(f"/public/getname-validation/{token}").get_json()["data"]

    assert data == {"valid": False, "reason": "expired"}


# --- what to test -----------------------------------------------------------


def test_getname_behind_a_path_prefix(client, getname_setup):
    """The health check is at the root of the getname, not of the host."""
    _set_getname(
        config={"type": "default"},
        memory={"value": "https://gw.example.org/getname/patient-name/{idPatient}"},
    )
    token = _create_link()

    data = client.get(f"/public/getname-validation/{token}").get_json()["data"]

    assert data["baseUrl"] == "https://gw.example.org/getname/"


def test_auth_getname_asks_for_a_token(client, getname_setup):
    """Type auth: the lookup step runs with a token; the secret never leaves."""
    _set_getname(
        config={"type": "auth", "secret": GETNAME_SECRET},
        memory={"value": NAME_URL},
    )
    token = _create_link()

    response = client.get(f"/public/getname-validation/{token}")

    data = response.get_json()["data"]
    assert data["getnameType"] == "auth"
    assert data["lookup"] == "token"
    assert GETNAME_SECRET not in response.get_data(as_text=True)


@pytest.mark.parametrize("getname_type", ["proxy", "getname-proxy"])
def test_proxied_getname_has_nothing_for_the_browser(
    client, getname_setup, getname_type
):
    """Names that come through the backend: no url is handed to the page."""
    _set_getname(config={"type": getname_type}, memory={"value": NAME_URL})
    token = _create_link()

    data = client.get(f"/public/getname-validation/{token}").get_json()["data"]

    assert data["mode"] == "backend"
    assert data["getnameType"] == "proxy"
    assert data["baseUrl"] is None
    assert data["nameUrl"] is None
    assert data["lookup"] == "skip"


@pytest.mark.parametrize(
    "memory",
    [
        None,
        {},
        {"value": "http://localhost/{idPatient}"},
        {"value": "https://getname.example.org:port/patient-name/{idPatient}"},
        {"value": "ftp://getname.example.org/patient-name/{idPatient}"},
        {"value": "not a url"},
    ],
)
def test_getname_without_url_is_unconfigured(client, getname_setup, memory):
    """No url a browser can call: the page reports it instead of testing."""
    _set_getname(config=None, memory=memory)
    token = _create_link()

    data = client.get(f"/public/getname-validation/{token}").get_json()["data"]

    assert data["valid"] is True
    assert data["mode"] == "unconfigured"
    assert data["baseUrl"] is None


def test_custom_headers_are_never_handed_out(client, getname_setup):
    """Headers of an older setup are a credential: the lookup is skipped."""
    _set_getname(
        config={"type": "default"},
        memory={"value": NAME_URL, "headers": {"Authorization": "zztest-header"}},
    )
    token = _create_link()

    response = client.get(f"/public/getname-validation/{token}")

    assert response.get_json()["data"]["lookup"] == "skip"
    # the page is told they exist (it cannot judge the authentication without
    # them), never what they are
    assert response.get_json()["data"]["customHeaders"] is True
    assert "zztest-header" not in response.get_data(as_text=True)


# --- the getname token ------------------------------------------------------


def test_auth_token_is_accepted_by_the_getname(client, getname_setup):
    """Signed with the schema's secret, issuer noharm, about a minute of life."""
    _set_getname(
        config={"type": "auth", "secret": GETNAME_SECRET},
        memory={"value": NAME_URL},
    )
    token = _create_link()

    response = client.post(f"/public/getname-validation/{token}/auth-token")

    assert response.status_code == 200
    payload = jwt.decode(
        response.get_json()["data"]["token"],
        GETNAME_SECRET,
        algorithms=["HS256"],
        issuer="noharm",
    )
    life = payload["exp"] - datetime.now(tz=timezone.utc).timestamp()
    assert 0 < life <= getname_validation_service.AUTH_TOKEN_SECONDS


def test_auth_token_only_for_a_getname_that_uses_one(client, getname_setup):
    """Type default: there is no token to give."""
    token = _create_link()

    response = client.post(f"/public/getname-validation/{token}/auth-token")

    assert response.status_code == 400


def test_auth_token_needs_a_valid_link(client, getname_setup):
    """An expired link gives no getname token."""
    _set_getname(
        config={"type": "auth", "secret": GETNAME_SECRET},
        memory={"value": NAME_URL},
    )
    token = _create_link(expires_in=timedelta(minutes=-1))

    for candidate in (token, "1-" + "f" * 48, "junk"):
        response = client.post(f"/public/getname-validation/{candidate}/auth-token")

        assert response.status_code == 401


# --- the result -------------------------------------------------------------


def test_result_is_saved_as_the_contract_says(client, getname_setup):
    """The row the admin project lists: its shape is a contract."""
    token = _create_link()

    response = _post_result(client, token, odoo=_odoo())

    assert response.status_code == 200
    assert response.get_json()["data"] == {
        "saved": True,
        "status": "passed",
        "ticket": "T4321",
        "runs": 1,
        "maxRuns": getname_validation_service.MAX_RUNS,
    }

    [result] = _results()
    assert result["schema"] == "demo"
    assert result["created_by"] == CREATED_BY
    extra = result["extra"]
    assert extra["action"] == "validation_result"
    assert extra["link_id"] == int(token.split("-")[0])
    assert extra["status"] == "passed"
    assert extra["diagnosis"] == "ok"
    assert extra["getname_type"] == "default"
    assert extra["base_url"] == "https://getname.example.org/"
    assert extra["ticket_id"] == 4321
    assert extra["ticket_ref"] == "T4321"
    assert extra["checks"][0] == {
        "id": "reachability",
        "status": "passed",
        "code": None,
        "http_status": 200,
        "duration_ms": 42,
        "detail": None,
    }
    assert extra["environment"]["permissions"] == {"local-network-access": "granted"}


def test_first_run_opens_the_ticket(client, getname_setup):
    """Ticket of type Validação, of the schema, requested by who made the link."""
    token = _create_link()
    odoo = _odoo()

    _post_result(client, token, odoo=odoo)

    [created] = _calls(odoo, "helpdesk.ticket", "web_save")
    ticket = created.kwargs["payload"][1]
    # the link's marker in the title is how the ticket is found again
    assert ticket["name"] == (
        f"[Validação] Getname demo (link {token.split('-')[0]}): Passou"
    )
    assert ticket["x_studio_schema_1"] == "demo"
    assert ticket["x_studio_tipo_chamado"] == 5
    assert ticket["partner_email"] == "demo"
    assert "Getname acessível e funcionando" in ticket["description"]
    assert "https://getname.example.org/" in ticket["description"]
    assert not _calls(odoo, "mail.message", "create")


def test_next_runs_go_to_the_same_ticket(client, getname_setup):
    """One ticket per link: a new run is a note and the title follows it."""
    token = _create_link()
    _post_result(client, token, odoo=_odoo())
    odoo = _odoo()
    failed = dict(
        PASSED_RESULT,
        status="failed",
        diagnosis="unreachable_timeout",
        checks=[{"id": "reachability", "status": "failed", "code": "timeout"}],
    )

    response = _post_result(client, token, payload=failed, odoo=odoo)

    assert response.get_json()["data"]["ticket"] == "T4321"
    assert response.get_json()["data"]["runs"] == 2
    assert not _calls(odoo, "helpdesk.ticket", "web_save")
    [note] = _calls(odoo, "mail.message", "create")
    assert note.kwargs["payload"][0]["res_id"] == 4321
    assert "Sem resposta do getname" in note.kwargs["payload"][0]["body"]
    [renamed] = _calls(odoo, "helpdesk.ticket", "write")
    assert renamed.kwargs["payload"] == [
        [4321],
        {"name": f"[Validação] Getname demo (link {token.split('-')[0]}): Falhou"},
    ]
    assert [r["extra"]["ticket_id"] for r in _results()] == [4321, 4321]


def test_what_the_person_saw_names_the_cause_on_the_ticket(client, getname_setup):
    """A failed connection has no reason for the page: the answer to "what
    showed up in the tab" comes as a check and is readable on the ticket."""
    token = _create_link()
    odoo = _odoo()
    payload = dict(
        PASSED_RESULT,
        status="failed",
        diagnosis="certificate",
        checks=[
            {"id": "manual", "status": "warning", "code": "saw_security_warning"},
            {"id": "reachability", "status": "failed", "code": "unreachable"},
        ],
    )

    response = _post_result(client, token, payload=payload, odoo=odoo)

    assert response.get_json()["data"]["status"] == "failed"
    description = _calls(odoo, "helpdesk.ticket", "web_save")[0].kwargs["payload"][1][
        "description"
    ]
    assert "O navegador não aceita o certificado https do getname" in description
    assert "O que apareceu ao abrir o getname em uma aba" in description
    assert "Aviso de segurança (certificado)" in description
    assert _results()[0]["extra"]["checks"][0]["code"] == "saw_security_warning"


def test_ticket_carries_the_message_for_the_hospital_it(client, getname_setup):
    """The person who runs the test never contacts IT: when the cause is IT's
    to fix, the ticket brings the message for the NoHarm staff to send."""
    token = _create_link()
    odoo = _odoo()
    payload = dict(
        PASSED_RESULT,
        status="failed",
        diagnosis="unreachable_timeout",
        checks=[{"id": "reachability", "status": "failed", "code": "timeout"}],
    )

    _post_result(client, token, payload=payload, odoo=odoo)

    description = _calls(odoo, "helpdesk.ticket", "web_save")[0].kwargs["payload"][1][
        "description"
    ]
    assert "Mensagem sugerida para a TI do hospital" in description
    assert "Servidor do getname: getname.example.org, porta 443 (https)" in description
    assert "Site que faz as chamadas: https://app.example.com" in description
    assert "liberar o acesso da rede dos computadores" in description


def test_ticket_names_the_browser_in_words(client, getname_setup):
    """Name, version and system readable on the receipt and in the message for
    IT (the version decides which browser protections apply); the raw user
    agent stays next to them."""
    token = _create_link()
    odoo = _odoo()
    payload = dict(
        PASSED_RESULT,
        status="failed",
        diagnosis="local_network_denied",
        checks=[
            {"id": "reachability", "status": "failed", "code": "local_network_denied"}
        ],
    )

    _post_result(client, token, payload=payload, odoo=odoo)

    description = _calls(odoo, "helpdesk.ticket", "web_save")[0].kwargs["payload"][1][
        "description"
    ]
    assert "Navegador</strong></td><td>Google Chrome 142.0.7444.60" in description
    assert "Sistema operacional</strong></td><td>Windows 11" in description
    assert "User agent</strong></td><td>Mozilla/5.0 (test)" in description
    assert (
        "Navegador usado no teste: Google Chrome 142.0.7444.60 em Windows 11."
        in description
    )
    assert _results()[0]["extra"]["environment"]["browser"] == (
        "Google Chrome 142.0.7444.60"
    )


def test_ticket_shows_where_the_test_came_from(client, getname_setup):
    """The public address of who tested: on the receipt and in the message for
    IT, and only there - the result row, which admin lists, does not keep it."""
    token = _create_link()
    odoo = _odoo()
    payload = dict(
        PASSED_RESULT,
        status="failed",
        diagnosis="unreachable_timeout",
        checks=[{"id": "reachability", "status": "failed", "code": "timeout"}],
    )

    _post_result(client, token, payload=payload, odoo=odoo)

    description = _calls(odoo, "helpdesk.ticket", "web_save")[0].kwargs["payload"][1][
        "description"
    ]
    assert f"IP público de quem testou</strong></td><td>{CLIENT_IP}" in description
    assert f"pelo IP público {CLIENT_IP}" in description
    assert CLIENT_IP not in json.dumps(_results()[0]["extra"])


def test_spoofed_forwarded_header_is_not_the_address(client, getname_setup):
    """The leftmost X-Forwarded-For entry is whatever the caller wrote."""
    token = _create_link()
    odoo = _odoo()

    with patch.object(
        getname_validation_service.odoo_client, "get_client", return_value=odoo
    ):
        client.post(
            f"/public/getname-validation/{token}/result",
            json=PASSED_RESULT,
            environ_base={"REMOTE_ADDR": CLIENT_IP},
            headers={"X-Forwarded-For": "198.51.100.99"},
        )

    description = _calls(odoo, "helpdesk.ticket", "web_save")[0].kwargs["payload"][1][
        "description"
    ]
    assert CLIENT_IP in description
    assert "198.51.100.99" not in description


def test_address_that_is_not_one_is_left_out(client, getname_setup):
    """Nothing but an ip address is written as one."""
    token = _create_link()
    odoo = _odoo()

    _post_result(client, token, odoo=odoo, remote_addr="<script>")

    description = _calls(odoo, "helpdesk.ticket", "web_save")[0].kwargs["payload"][1][
        "description"
    ]
    assert "IP público de quem testou</strong></td><td>-" in description
    assert "script" not in description


def test_no_message_for_it_when_the_fix_is_not_theirs(client, getname_setup):
    """A passed run, or a cause NoHarm fixes by itself, suggests no message."""
    token = _create_link()
    odoo = _odoo()
    cors = dict(
        PASSED_RESULT,
        status="failed",
        diagnosis="cors",
        checks=[{"id": "reachability", "status": "failed", "code": "cors"}],
    )

    _post_result(client, token, odoo=odoo)
    _post_result(client, token, payload=cors, odoo=odoo)

    opened = _calls(odoo, "helpdesk.ticket", "web_save")[0].kwargs["payload"][1]
    note = _calls(odoo, "mail.message", "create")[0].kwargs["payload"][0]
    assert "Mensagem sugerida" not in opened["description"]
    assert "Mensagem sugerida" not in note["body"]


def test_message_for_it_escapes_the_origin_the_page_sent(client, getname_setup):
    """The origin comes from an anonymous browser and lands in the helpdesk."""
    token = _create_link()
    odoo = _odoo()
    payload = dict(
        PASSED_RESULT,
        status="failed",
        diagnosis="dns",
        checks=[{"id": "reachability", "status": "failed", "code": "unreachable"}],
        environment={"pageOrigin": "<b>https://app.example.com</b>"},
    )

    _post_result(client, token, payload=payload, odoo=odoo)

    description = _calls(odoo, "helpdesk.ticket", "web_save")[0].kwargs["payload"][1][
        "description"
    ]
    assert "<b>https://app.example.com" not in description
    assert "&lt;b&gt;https://app.example.com" in description


def test_ticket_opened_and_never_recorded_is_found_again(client, getname_setup):
    """A request that died after opening the ticket (slow helpdesk, timeout)
    saved no row: the next run looks for the link's ticket in the helpdesk
    before opening one, so the link never gets a second ticket."""
    token = _create_link()
    odoo = _odoo(ticket_id=777, ticket_ref="T0777", existing=True)

    response = _post_result(client, token, odoo=odoo)

    assert response.get_json()["data"]["ticket"] == "T0777"
    assert not _calls(odoo, "helpdesk.ticket", "web_save")
    [searched] = [
        call
        for call in _calls(odoo, "helpdesk.ticket", "search_read")
        if _is_search_by_link(call.kwargs["payload"])
    ]
    assert searched.kwargs["payload"][0] == [
        ["x_studio_schema_1", "=", "demo"],
        ["name", "like", f"(link {token.split('-')[0]})"],
    ]
    [note] = _calls(odoo, "mail.message", "create")
    assert note.kwargs["payload"][0]["res_id"] == 777
    assert _results()[0]["extra"]["ticket_id"] == 777

    # once a row has it, the helpdesk is not searched again
    odoo = _odoo(ticket_id=777, ticket_ref="T0777", existing=True)
    _post_result(client, token, odoo=odoo)
    assert not _calls(odoo, "helpdesk.ticket", "search_read")


def test_ticket_is_recorded_even_if_its_reference_cannot_be_read(
    client, getname_setup
):
    """The ticket exists once it was created: a failure right after must not
    leave it unknown to the link."""
    token = _create_link()
    odoo = _odoo()
    answer = odoo.side_effect

    def execute(model, action, payload, options):
        """The helpdesk, failing when a ticket is read by its id"""
        if (
            model == "helpdesk.ticket"
            and action == "search_read"
            and not _is_search_by_link(payload)
        ):
            raise ConnectionError("helpdesk down")
        return answer(model=model, action=action, payload=payload, options=options)

    odoo.side_effect = execute

    response = _post_result(client, token, odoo=odoo)

    assert response.get_json()["data"]["ticket"] == "4321"
    assert _results()[0]["extra"]["ticket_id"] == 4321


def test_helpdesk_is_not_called_past_its_time_budget(client, getname_setup):
    """The page is waiting behind a gateway timeout: once the budget is spent
    no helpdesk call is started and the run is saved without the ticket."""
    token = _create_link()
    odoo = _odoo()

    with patch.object(getname_validation_service, "TICKET_BUDGET_SECONDS", -1):
        response = _post_result(client, token, odoo=odoo)

    assert response.status_code == 200
    assert response.get_json()["data"] == {
        "saved": True,
        "status": "passed",
        "ticket": None,
        "runs": 1,
        "maxRuns": getname_validation_service.MAX_RUNS,
    }
    assert not odoo.called


def test_each_link_has_its_own_ticket(client, getname_setup):
    """Another link of the same schema does not reuse the ticket."""
    _post_result(client, _create_link(), odoo=_odoo())
    odoo = _odoo(ticket_id=5000, ticket_ref="T5000")

    response = _post_result(client, _create_link(), odoo=odoo)

    assert response.get_json()["data"]["ticket"] == "T5000"
    assert response.get_json()["data"]["runs"] == 1
    assert len(_calls(odoo, "helpdesk.ticket", "web_save")) == 1


def test_helpdesk_down_never_loses_the_run(client, getname_setup):
    """Saved without a ticket; the next run opens it."""
    token = _create_link()
    broken = MagicMock(side_effect=ConnectionError("helpdesk down"))

    for odoo in (None, broken):
        response = _post_result(client, token, odoo=odoo)

        assert response.status_code == 200
        assert response.get_json()["data"]["saved"] is True
        assert response.get_json()["data"]["ticket"] is None

    odoo = _odoo()
    response = _post_result(client, token, odoo=odoo)

    assert response.get_json()["data"]["ticket"] == "T4321"
    assert len(_calls(odoo, "helpdesk.ticket", "web_save")) == 1
    assert [r["extra"]["ticket_id"] for r in _results()] == [None, None, 4321]


def test_a_failed_check_never_counts_as_passed(client, getname_setup):
    """The verdict is recomputed from the checks."""
    token = _create_link()
    payload = dict(
        PASSED_RESULT,
        checks=[{"id": "database", "status": "failed", "code": "unhealthy"}],
    )

    response = _post_result(client, token, payload=payload, odoo=_odoo())

    assert response.get_json()["data"]["status"] == "failed"
    assert _results()[0]["extra"]["status"] == "failed"


def test_receipt_escapes_what_the_page_sent(client, getname_setup):
    """The page is public and the receipt is rendered by the helpdesk."""
    token = _create_link()
    odoo = _odoo()
    payload = dict(
        PASSED_RESULT,
        checks=[
            {
                "id": "reachability",
                "status": "warning",
                "detail": "<script>alert(1)</script>",
            }
        ],
        environment={"userAgent": "<img src=x onerror=alert(1)>"},
    )

    _post_result(client, token, payload=payload, odoo=odoo)

    description = _calls(odoo, "helpdesk.ticket", "web_save")[0].kwargs["payload"][1][
        "description"
    ]
    assert "<script>" not in description
    assert "<img" not in description
    assert "&lt;script&gt;" in description


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"status": "great", "checks": []},
        {"status": "passed", "diagnosis": "DROP TABLE", "checks": []},
        {"status": "passed", "checks": [{"id": "x", "status": "maybe"}]},
        {"status": "passed", "checks": [{"id": "x", "status": "passed"}] * 13},
        {
            "status": "passed",
            "checks": [{"id": "x", "status": "passed", "detail": "a" * 301}],
        },
        # the permission map takes known states and short names only
        {
            "status": "passed",
            "checks": [],
            "environment": {"permissions": {"local-network": "a" * 5000}},
        },
        {
            "status": "passed",
            "checks": [],
            "environment": {"permissions": {"a" * 5000: "granted"}},
        },
        # a body that is not an object
        [1],
        "text",
    ],
)
def test_invalid_result_is_refused(client, getname_setup, payload):
    """Closed vocabularies and bounded strings: nothing else is stored."""
    token = _create_link()
    odoo = _odoo()

    response = _post_result(client, token, payload=payload, odoo=odoo)

    assert response.status_code == 400
    assert _results() == []
    assert not odoo.called


def test_result_needs_a_valid_link(client, getname_setup):
    """No link, no row and no ticket."""
    odoo = _odoo()
    expired = _create_link(expires_in=timedelta(minutes=-1))

    for token in (expired, "1-" + "f" * 48, "junk"):
        response = _post_result(client, token, odoo=odoo)

        assert response.status_code == 401

    assert _results() == []
    assert not odoo.called


def test_link_is_spent_after_the_run_limit(client, getname_setup):
    """The page is public: a link saves a bounded number of runs."""
    token = _create_link()

    with patch.object(getname_validation_service, "MAX_RUNS", 2):
        assert _post_result(client, token, odoo=None).status_code == 200
        assert _post_result(client, token, odoo=None).status_code == 200
        assert _post_result(client, token, odoo=None).status_code == 401

        data = client.get(f"/public/getname-validation/{token}").get_json()["data"]
        assert data == {"valid": False, "reason": "exhausted"}

        auth = client.post(f"/public/getname-validation/{token}/auth-token")
        assert auth.status_code == 401

    assert len(_results()) == 2
