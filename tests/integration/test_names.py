"""Integration tests for the /names endpoints (patient name resolution).

Patient names are never stored in NoHarm's own database — they are fetched on
demand from whatever the client (hospital) runs. ``name_service`` picks a
strategy from the tenant's ``getname`` configuration in
``public.schema_config.configuracao``:

* ``token.url`` starting with ``dy`` → DynamoDB;
* ``internal: true``               → NoHarm's own name API (JWT);
* ``type: "getname-proxy"``        → proxy API (X-API-Key);
* otherwise                       → external API (OAuth token).

Because a name lookup sits in front of every patient list, the routes are
written to degrade instead of failing: a lookup that cannot be resolved returns
the placeholder ``Paciente <id>`` rather than an error page.

These are integration tests: they authenticate for real, go through the routes
and read the real ``schema_config`` row. Only the outbound boundary (``aws`` /
``requests``) is patched, so no test reaches DynamoDB or an external host. The
``getname_config`` fixture writes the tenant configuration and always restores
the original value, so the tests are re-runnable and leave no residue.
"""

import json
from unittest.mock import MagicMock, patch
from urllib.parse import quote

import jwt
import pytest
from sqlalchemy import text

from services import name_service
from tests.conftest import session, session_commit

# Any patient id works: nothing about the lookup touches the local patient row.
PATIENT_ID = 1

# HS256 keys, long enough not to trip PyJWT's short-key warning.
GETNAME_SECRET = "zztest-getname-secret-0123456789abcdef"
CLIENT_SECRET = "zztest-client-secret-0123456789abcdef"
WRONG_SECRET = "zztest-wrong-secret-0123456789abcdef"


@pytest.fixture
def getname_config():
    """Set ``demo``'s getname configuration, restoring the original after.

    Yields a setter so each test declares the strategy it needs. Tests that
    never call the setter exercise the unconfigured tenant (the seed state).
    """
    original = session.execute(
        text("SELECT configuracao FROM public.schema_config WHERE schema_name = 'demo'")
    ).scalar()

    def _set(getname: dict):
        session.execute(
            text(
                "UPDATE public.schema_config SET configuracao = CAST(:config AS jsonb) "
                "WHERE schema_name = 'demo'"
            ),
            {"config": json.dumps({"getname": getname})},
        )
        session_commit()

    yield _set

    session.execute(
        text(
            "UPDATE public.schema_config SET configuracao = CAST(:config AS jsonb) "
            "WHERE schema_name = 'demo'"
        ),
        {"config": json.dumps(original) if original is not None else None},
    )
    session_commit()


@pytest.fixture
def no_getname_config(getname_config):
    """Guarantee ``demo`` has no getname configuration for this test."""
    session.execute(
        text(
            "UPDATE public.schema_config SET configuracao = NULL "
            "WHERE schema_name = 'demo'"
        )
    )
    session_commit()
    yield


# --------------------------------------------------------------------------
# authentication
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,url",
    [
        ("get", f"/names/{PATIENT_ID}"),
        ("post", "/names"),
        ("get", "/names/auth-token"),
        ("get", "/names/search/ana"),
    ],
)
def test_names_endpoints_require_authentication(client, method, url):
    """Every /names endpoint is behind @jwt_required [401 UNAUTHORIZED]."""
    response = getattr(client, method)(url)

    assert response.status_code == 401


# --------------------------------------------------------------------------
# search term validation (route-level allow-list)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "term,description",
    [
        ("ana;silva", "semicolon"),
        ("ana+silva", "plus sign"),
        ("ana%silva", "percent sign"),
        ("ana_silva", "underscore"),
        ("ana.silva", "dot"),
        ("ana@silva", "at sign"),
        ("ana*", "asterisk"),
        ("a" * 101, "longer than 100 characters"),
    ],
)
def test_search_rejects_terms_outside_the_allow_list(
    client, analyst_headers, term, description
):
    """A term with unexpected characters is refused before any lookup.

    The search term is interpolated into an upstream URL, so the route only
    lets through letters, digits, spaces, apostrophes and hyphens.
    """
    response = client.get(
        f"/names/search/{quote(term, safe='')}", headers=analyst_headers
    )

    assert response.status_code == 400, f"should reject {description}"
    assert response.get_json() == {"status": "error", "data": []}


@pytest.mark.parametrize(
    "term",
    [
        "ana",
        "Ana Maria",
        "João Gonçalves",
        "d'Ávila",
        "Silva-Souza",
        "Paciente 42",
        "a" * 100,
    ],
)
def test_search_accepts_valid_terms_and_forwards_them_unchanged(
    client, analyst_headers, getname_config, term
):
    """An accepted term reaches the service exactly as typed.

    Accents, apostrophes, hyphens, digits and spaces are all legitimate in
    Brazilian patient names, so they must survive the allow-list.
    """
    getname_config({"internal": True, "url": "https://names.example/", "params": {}})

    with patch.object(
        name_service.NHInternalNameService, "search_by_name", return_value=[]
    ) as search_by_name:
        response = client.get(
            f"/names/search/{quote(term, safe='')}", headers=analyst_headers
        )

    assert response.status_code == 200
    search_by_name.assert_called_once()
    assert search_by_name.call_args.args[0] == term


# --------------------------------------------------------------------------
# unconfigured tenant — the endpoints degrade instead of failing
# --------------------------------------------------------------------------


def test_single_name_without_configuration_returns_the_placeholder(
    client, analyst_headers, no_getname_config
):
    """With no getname config the UI still gets a displayable name [400]."""
    response = client.get(f"/names/{PATIENT_ID}", headers=analyst_headers)

    assert response.status_code == 400
    assert response.get_json() == {
        "status": "error",
        "idPatient": PATIENT_ID,
        "name": f"Paciente {PATIENT_ID}",
    }


def test_multiple_names_without_configuration_returns_an_empty_list(
    client, analyst_headers, no_getname_config
):
    """The batch endpoint reports the failure but never breaks the caller."""
    response = client.post(
        "/names", headers=analyst_headers, json={"patients": [1, 2, 3]}
    )

    assert response.status_code == 500
    assert response.get_json() == []


def test_search_without_configuration_returns_an_empty_result_set(
    client, analyst_headers, no_getname_config
):
    """A failed search is reported in the body, with 200 so the UI can render."""
    response = client.get("/names/search/ana", headers=analyst_headers)

    assert response.status_code == 200
    assert response.get_json() == {"status": "error", "data": []}


def test_auth_token_without_configuration_is_rejected(
    client, analyst_headers, no_getname_config
):
    """No configuration means no signing key, so no token is issued [400]."""
    response = client.get("/names/auth-token", headers=analyst_headers)

    assert response.status_code == 400
    assert response.get_json()["status"] == "error"


# --------------------------------------------------------------------------
# auth-token — the short-lived token the frontend uses against the name API
# --------------------------------------------------------------------------


def test_auth_token_is_signed_with_the_tenant_secret(
    client, analyst_headers, getname_config
):
    """The token is an HS256 JWT signed with the tenant's getname secret."""
    secret = GETNAME_SECRET
    getname_config({"secret": secret, "params": {}})

    response = client.get("/names/auth-token", headers=analyst_headers)

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "success"

    claims = jwt.decode(body["data"], key=secret, algorithms=["HS256"])
    assert claims["iss"] == "noharm"
    # short-lived by design (2 minutes)
    assert claims["exp"] > 0


def test_auth_token_rejects_a_token_signed_with_another_secret(
    client, analyst_headers, getname_config
):
    """The signature is real: a different key does not verify."""
    getname_config({"secret": GETNAME_SECRET, "params": {}})

    response = client.get("/names/auth-token", headers=analyst_headers)

    assert response.status_code == 200
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(
            response.get_json()["data"],
            key=WRONG_SECRET,
            algorithms=["HS256"],
        )


def test_auth_token_without_a_secret_is_rejected(
    client, analyst_headers, getname_config
):
    """A getname block with no ``secret`` cannot sign a token [400]."""
    getname_config({"url": "https://names.example/", "params": {}})

    response = client.get("/names/auth-token", headers=analyst_headers)

    assert response.status_code == 400
    assert response.get_json()["status"] == "error"


# --------------------------------------------------------------------------
# strategy selection — the configuration decides which backend is called
# --------------------------------------------------------------------------


def test_dynamodb_configuration_resolves_the_name_from_dynamodb(
    client, analyst_headers, getname_config
):
    """A ``dy:``-prefixed token url routes the lookup to DynamoDB."""
    getname_config({"token": {"url": "dy:zztest-names", "params": {}}, "params": {}})

    with patch("services.name_service.aws") as mock_aws:
        table = mock_aws.get_resource.return_value.Table.return_value
        table.get_item.return_value = {
            "Item": {"schema_fkpessoa": str(PATIENT_ID), "nome": "Ana Maria"}
        }

        response = client.get(f"/names/{PATIENT_ID}", headers=analyst_headers)

    assert response.status_code == 200
    assert response.get_json() == {
        "status": "success",
        "idPatient": PATIENT_ID,
        "name": "Ana Maria",
        "data": None,
    }
    # the table name is taken from the configured token url
    mock_aws.get_resource.return_value.Table.assert_called_once_with("zztest-names")
    table.get_item.assert_called_once_with(
        Key={"schema_fkpessoa": str(PATIENT_ID)}
    )


def test_dynamodb_name_is_html_escaped(client, analyst_headers, getname_config):
    """Names come from an external system, so they are escaped on the way out."""
    getname_config({"token": {"url": "dy:zztest-names", "params": {}}, "params": {}})

    with patch("services.name_service.aws") as mock_aws:
        table = mock_aws.get_resource.return_value.Table.return_value
        table.get_item.return_value = {
            "Item": {
                "schema_fkpessoa": str(PATIENT_ID),
                "nome": "Maria <script>alert(1)</script> & 'cia'",
                "fone": "<b>11999</b>",
            }
        }

        response = client.get(f"/names/{PATIENT_ID}", headers=analyst_headers)

    body = response.get_json()
    assert response.status_code == 200
    assert "<script>" not in body["name"]
    assert body["name"] == (
        "Maria &lt;script&gt;alert(1)&lt;/script&gt; &amp; &#39;cia&#39;"
    )
    # extra fields are escaped too, and the key columns are stripped
    assert body["data"] == {"fone": "&lt;b&gt;11999&lt;/b&gt;"}


def test_dynamodb_unknown_patient_returns_the_placeholder(
    client, analyst_headers, getname_config
):
    """A patient missing from the table falls back to ``Paciente <id>``."""
    getname_config({"token": {"url": "dy:zztest-names", "params": {}}, "params": {}})

    with patch("services.name_service.aws") as mock_aws:
        table = mock_aws.get_resource.return_value.Table.return_value
        table.get_item.return_value = {}

        response = client.get(f"/names/{PATIENT_ID}", headers=analyst_headers)

    assert response.status_code == 400
    assert response.get_json() == {
        "status": "error",
        "idPatient": PATIENT_ID,
        "name": f"Paciente {PATIENT_ID}",
    }


def test_dynamodb_failure_is_swallowed_into_the_placeholder(
    client, analyst_headers, getname_config
):
    """A DynamoDB outage must not take the patient list down with it."""
    getname_config({"token": {"url": "dy:zztest-names", "params": {}}, "params": {}})

    with patch("services.name_service.aws") as mock_aws:
        table = mock_aws.get_resource.return_value.Table.return_value
        table.get_item.side_effect = RuntimeError("dynamo is down")

        response = client.get(f"/names/{PATIENT_ID}", headers=analyst_headers)

    assert response.status_code == 400
    assert response.get_json()["name"] == f"Paciente {PATIENT_ID}"


def test_dynamodb_does_not_support_search(client, analyst_headers, getname_config):
    """Search is unavailable on DynamoDB, reported as an empty success."""
    getname_config({"token": {"url": "dy:zztest-names", "params": {}}, "params": {}})

    with patch("services.name_service.aws"):
        response = client.get("/names/search/ana", headers=analyst_headers)

    assert response.status_code == 200
    assert response.get_json() == {"status": "success", "data": []}


def test_proxy_configuration_sends_the_api_key(
    client, analyst_headers, getname_config
):
    """``type: getname-proxy`` calls the proxy API with the X-API-Key header."""
    getname_config(
        {
            "type": "getname-proxy",
            "url": "https://proxy.example/getname",
            "xapikey": "zztest-api-key",
            "params": {"tenant": "demo"},
        }
    )

    with patch("services.name_service.requests") as mock_requests:
        mock_requests.get.return_value = _ok_response(
            {"data": [{"idPatient": PATIENT_ID, "name": "Ana Maria"}]}
        )

        response = client.get(f"/names/{PATIENT_ID}", headers=analyst_headers)

    assert response.status_code == 200
    assert response.get_json()["name"] == "Ana Maria"

    call = mock_requests.get.call_args
    assert call.args[0] == "https://proxy.example/getname"
    assert call.kwargs["headers"] == {"X-API-Key": "zztest-api-key"}
    # configured params are preserved alongside the patient id
    assert call.kwargs["params"] == {"tenant": "demo", "cd_paciente": PATIENT_ID}


def test_internal_configuration_sends_a_bearer_token(
    client, analyst_headers, getname_config
):
    """``internal: true`` calls NoHarm's own name API with a signed token."""
    secret = CLIENT_SECRET
    getname_config(
        {
            "internal": True,
            "url": "https://names.example/",
            "token": {"url": "internal", "params": {"client_secret": secret}},
            "params": {},
        }
    )

    with patch("services.name_service.requests") as mock_requests:
        mock_requests.get.return_value = _ok_response(
            {"idPatient": PATIENT_ID, "name": "Ana Maria", "data": {"fone": "119"}}
        )

        response = client.get(f"/names/{PATIENT_ID}", headers=analyst_headers)

    assert response.status_code == 200
    assert response.get_json() == {
        "status": "success",
        "idPatient": PATIENT_ID,
        "name": "Ana Maria",
        "data": {"fone": "119"},
    }

    call = mock_requests.get.call_args
    assert call.args[0] == f"https://names.example/patient-name/{PATIENT_ID}"

    # the Authorization header carries a JWT signed with the configured secret
    token = call.kwargs["headers"]["Authorization"].removeprefix("Bearer ")
    assert jwt.decode(token, key=secret, algorithms=["HS256"])["iss"] == "noharm"


def test_internal_search_returns_sorted_results(
    client, analyst_headers, getname_config
):
    """Search results are mapped, escaped and sorted by name."""
    getname_config(
        {
            "internal": True,
            "url": "https://names.example/",
            "token": {"url": "internal", "params": {"client_secret": CLIENT_SECRET}},
            "params": {},
        }
    )

    with patch("services.name_service.requests") as mock_requests:
        mock_requests.get.return_value = _ok_response(
            {
                "results": [
                    {
                        "name": "Zulmira <b>Souza</b>",
                        "idPatient": 2,
                        "dtnascimento": "1970-01-01",
                        "cpf": "222",
                    },
                    {
                        "name": "Ana Maria",
                        "idPatient": 1,
                        "dtnascimento": "1980-05-04",
                        "cpf": "111",
                    },
                ]
            }
        )

        response = client.get("/names/search/ana", headers=analyst_headers)

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert [p["name"] for p in data] == [
        "Ana Maria",
        "Zulmira &lt;b&gt;Souza&lt;/b&gt;",
    ]
    assert data[0] == {
        "name": "Ana Maria",
        "idPatient": 1,
        "birthdate": "1980-05-04",
        "number": "111",
    }

    # the term is URL-quoted into the upstream path
    assert (
        mock_requests.get.call_args.args[0]
        == "https://names.example/search-name/ana"
    )


def test_internal_search_is_capped(client, analyst_headers, getname_config):
    """A huge upstream result set is truncated before reaching the UI."""
    getname_config(
        {
            "internal": True,
            "url": "https://names.example/",
            "token": {"url": "internal", "params": {"client_secret": CLIENT_SECRET}},
            "params": {},
        }
    )

    upstream = [
        {
            "name": f"Paciente {i:04}",
            "idPatient": i,
            "dtnascimento": "1980-05-04",
            "cpf": str(i),
        }
        for i in range(name_service.MAX_SEARCH_RESULTS + 50)
    ]

    with patch("services.name_service.requests") as mock_requests:
        mock_requests.get.return_value = _ok_response({"results": upstream})

        response = client.get("/names/search/paciente", headers=analyst_headers)

    assert len(response.get_json()["data"]) == name_service.MAX_SEARCH_RESULTS


def test_internal_search_upstream_error_returns_an_empty_list(
    client, analyst_headers, getname_config
):
    """A non-200 from the name API yields no results rather than an error."""
    getname_config(
        {
            "internal": True,
            "url": "https://names.example/",
            "token": {"url": "internal", "params": {"client_secret": CLIENT_SECRET}},
            "params": {},
        }
    )

    with patch("services.name_service.requests") as mock_requests:
        mock_requests.get.return_value = _error_response(503)

        response = client.get("/names/search/ana", headers=analyst_headers)

    assert response.status_code == 200
    assert response.get_json() == {"status": "success", "data": []}


# --------------------------------------------------------------------------
# batch lookup — chunking and ordering
# --------------------------------------------------------------------------


def test_multiple_names_are_requested_in_configured_chunks(
    client, analyst_headers, getname_config
):
    """The id list is split by ``chunk_size`` before hitting the backend."""
    getname_config(
        {
            "token": {"url": "dy:zztest-names", "params": {}},
            "params": {},
            "chunk_size": 2,
        }
    )

    with patch.object(
        name_service.DynamoDBNameService, "get_multiple_names"
    ) as get_multiple:
        get_multiple.side_effect = lambda ids: [
            {"status": "success", "idPatient": i, "name": f"Paciente {i}"} for i in ids
        ]

        response = client.post(
            "/names", headers=analyst_headers, json={"patients": [1, 2, 3, 4, 5]}
        )

    assert response.status_code == 200
    assert [c.args[0] for c in get_multiple.call_args_list] == [[1, 2], [3, 4], [5]]
    # the chunks are concatenated back in the requested order
    assert [p["idPatient"] for p in response.get_json()] == [1, 2, 3, 4, 5]


def test_multiple_names_use_a_default_chunk_size(
    client, analyst_headers, getname_config
):
    """Without ``chunk_size`` the list is split into batches of 200."""
    getname_config({"token": {"url": "dy:zztest-names", "params": {}}, "params": {}})

    with patch.object(
        name_service.DynamoDBNameService, "get_multiple_names"
    ) as get_multiple:
        get_multiple.side_effect = lambda ids: [
            {"status": "success", "idPatient": i, "name": f"Paciente {i}"} for i in ids
        ]

        response = client.post(
            "/names",
            headers=analyst_headers,
            json={"patients": list(range(1, 202))},
        )

    assert response.status_code == 200
    assert [len(c.args[0]) for c in get_multiple.call_args_list] == [200, 1]
    assert len(response.get_json()) == 201


def test_multiple_names_with_an_empty_list_calls_no_backend(
    client, analyst_headers, getname_config
):
    """An empty request short-circuits: no chunk, no upstream call."""
    getname_config({"token": {"url": "dy:zztest-names", "params": {}}, "params": {}})

    with patch.object(
        name_service.DynamoDBNameService, "get_multiple_names"
    ) as get_multiple:
        response = client.post("/names", headers=analyst_headers, json={"patients": []})

    assert response.status_code == 200
    assert response.get_json() == []
    get_multiple.assert_not_called()


def test_multiple_names_defaults_to_an_empty_list_when_patients_is_omitted(
    client, analyst_headers, getname_config
):
    """A payload without ``patients`` is treated as an empty request."""
    getname_config({"token": {"url": "dy:zztest-names", "params": {}}, "params": {}})

    with patch.object(
        name_service.DynamoDBNameService, "get_multiple_names"
    ) as get_multiple:
        response = client.post("/names", headers=analyst_headers, json={})

    assert response.status_code == 200
    assert response.get_json() == []
    get_multiple.assert_not_called()


def test_multiple_names_fills_placeholders_for_unknown_patients(
    client, analyst_headers, getname_config
):
    """Ids missing upstream still come back, as placeholders, in order."""
    getname_config({"token": {"url": "dy:zztest-names", "params": {}}, "params": {}})

    with patch("services.name_service.aws") as mock_aws:
        dynamodb = mock_aws.get_resource.return_value
        dynamodb.batch_get_item.return_value = {
            "Responses": {
                "zztest-names": [{"schema_fkpessoa": "2", "nome": "Ana Maria"}]
            }
        }

        response = client.post(
            "/names", headers=analyst_headers, json={"patients": [1, 2]}
        )

    assert response.status_code == 200
    assert response.get_json() == [
        {"status": "error", "idPatient": 1, "name": "Paciente 1"},
        {
            "status": "success",
            "idPatient": 2,
            "name": "Ana Maria",
            "data": None,
        },
    ]


# --------------------------------------------------------------------------
# unexpected failures never escape as a 500 HTML page
# --------------------------------------------------------------------------


def test_single_name_unexpected_failure_returns_the_placeholder(
    client, analyst_headers, getname_config
):
    """An unexpected error in the service is still a usable response."""
    getname_config({"token": {"url": "dy:zztest-names", "params": {}}, "params": {}})

    with patch.object(name_service, "get_patient_name") as get_patient_name:
        get_patient_name.side_effect = RuntimeError("boom")

        response = client.get(f"/names/{PATIENT_ID}", headers=analyst_headers)

    assert response.status_code == 400
    assert response.get_json() == {
        "status": "error",
        "idPatient": PATIENT_ID,
        "name": f"Paciente {PATIENT_ID}",
    }


def test_auth_token_unexpected_failure_is_reported_as_an_error(
    client, analyst_headers, getname_config
):
    """A failure while signing is reported without leaking the exception."""
    getname_config({"secret": GETNAME_SECRET, "params": {}})

    with patch.object(name_service, "generate_internal_token") as generate:
        generate.side_effect = RuntimeError("boom")

        response = client.get("/names/auth-token", headers=analyst_headers)

    assert response.status_code == 400
    body = response.get_json()
    assert body["status"] == "error"
    assert "boom" not in body["message"]


# --------------------------------------------------------------------------
# stub builders
# --------------------------------------------------------------------------


def _ok_response(payload):
    """Build a stub ``requests`` response with a 200 status and ``payload``."""
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = payload
    return response


def _error_response(status_code):
    """Build a stub ``requests`` response carrying ``status_code``."""
    response = MagicMock()
    response.status_code = status_code
    return response
