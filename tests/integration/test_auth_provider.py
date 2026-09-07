"""Integration tests for the OAUTH provider login feature.

Besides the local e-mail/password login, a tenant can delegate authentication to
an external identity provider. Two endpoints make up that flow:

* ``GET /auth-provider/<schema>`` publishes the tenant's OAUTH settings so the
  frontend knows where to send the user (and, for the two-legged variant, which
  flow to run);
* ``POST /auth-provider`` receives the provider's ``id_token`` and turns it into
  a NoHarm session — the same payload ``/authenticate`` returns.

The token is verified for real: the algorithm must be one of the allowed RSA
variants, the ``kid`` must match a key published in the ``oauth-keys`` memory,
and the signature and audience must check out against that key. Only then is the
e-mail claim mapped to a NoHarm user, which must already exist — OAUTH never
creates accounts. A tenant also has to carry the ``OAUTH`` feature flag unless
the user is a maintainer.

These tests sign real RS256 tokens with a throwaway key pair and publish its
public half as the tenant's JWK, so signature, ``kid`` and audience handling are
exercised end to end rather than mocked. Only the ``authentication_basic`` flow's
outbound call to the provider is patched, since that leg talks to a real host.
"""

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import text

from models.enums import FeatureEnum, MemoryEnum
from tests.conftest import session, session_commit
from utils import status

CLIENT_ID = "noharm-test-client"
CLIENT_SECRET = "noharm-test-secret"
KEY_ID = "test-key-1"
LOGIN_URL = "https://idp.example.com/oauth2/token"
AUTH_URL = "https://idp.example.com/oauth2/authorize?response_type=code"

# the demo user, as seeded — OAUTH maps an e-mail claim onto an existing account
DEMO_EMAIL = "demo"


@pytest.fixture(scope="module")
def rsa_key_pair():
    """A throwaway RSA key pair: private half signs tokens, public half is the JWK."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    jwk["kid"] = KEY_ID
    jwk["use"] = "sig"
    jwk["alg"] = "RS256"

    return private_key, jwk


def _make_token(private_key, *, claims=None, headers=None, algorithm="RS256"):
    """Sign an id_token for the test client, letting each test override the parts."""
    payload = {
        "aud": CLIENT_ID,
        "iss": "https://idp.example.com",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        "iat": datetime.now(timezone.utc),
        "email": DEMO_EMAIL,
        "name": "Fulano Beltrano",
    }
    payload.update(claims or {})

    return jwt.encode(
        payload,
        key=private_key,
        algorithm=algorithm,
        headers={"kid": KEY_ID, **(headers or {})},
    )


def _oauth_config(**overrides):
    """The tenant's oauth settings block, as stored in schema_config.configuracao."""
    config = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "login_url": LOGIN_URL,
        "auth_url": AUTH_URL,
        "company": "Hospital Teste",
        "email_attr": "email",
        "name_attr": "name",
    }
    config.update(overrides)
    return config


def _set_schema_oauth_config(oauth_config):
    """Write (or clear, when None) the oauth block on the demo tenant."""
    if oauth_config is None:
        value = None
    else:
        value = json.dumps({"oauth": oauth_config})

    session.execute(
        text(
            "UPDATE public.schema_config SET configuracao = CAST(:value AS jsonb) "
            "WHERE schema_name = 'demo'"
        ),
        {"value": value},
    )
    session_commit()


def _set_oauth_keys(keys):
    """Publish (or remove, when None) the tenant's JWK set in the oauth-keys memory."""
    session.execute(
        text("DELETE FROM demo.memoria WHERE tipo = :kind"),
        {"kind": MemoryEnum.OAUTH_KEYS.value},
    )

    if keys is not None:
        session.execute(
            text(
                "INSERT INTO demo.memoria (tipo, valor, update_at, update_by) "
                "VALUES (:kind, CAST(:value AS json), now(), 1)"
            ),
            {
                "kind": MemoryEnum.OAUTH_KEYS.value,
                "value": json.dumps({"keys": keys}),
            },
        )

    session_commit()


def _set_oauth_feature(enabled):
    """Add or remove the OAUTH flag on the tenant's features memory."""
    row = session.execute(
        text("SELECT valor FROM demo.memoria WHERE tipo = 'features'")
    ).first()

    features = list(row[0]) if row and row[0] else []

    if enabled and FeatureEnum.OAUTH.value not in features:
        features.append(FeatureEnum.OAUTH.value)
    if not enabled and FeatureEnum.OAUTH.value in features:
        features.remove(FeatureEnum.OAUTH.value)

    session.execute(
        text(
            "UPDATE demo.memoria SET valor = CAST(:value AS json) WHERE tipo = 'features'"
        ),
        {"value": json.dumps(features)},
    )
    session_commit()


@pytest.fixture
def oauth_tenant(rsa_key_pair):
    """Configure the demo tenant for OAUTH, then restore the seed state.

    Yields a setter so a test can narrow the config (a nonce requirement, the
    two-legged flow, a different e-mail attribute) on top of the working setup.
    """
    private_key, jwk = rsa_key_pair

    original_config = session.execute(
        text("SELECT configuracao FROM public.schema_config WHERE schema_name = 'demo'")
    ).scalar()
    original_features = session.execute(
        text("SELECT valor FROM demo.memoria WHERE tipo = 'features'")
    ).scalar()

    _set_schema_oauth_config(_oauth_config())
    _set_oauth_keys([jwk])
    _set_oauth_feature(True)

    def configure(*, oauth_config=..., keys=..., feature=...):
        if oauth_config is not ...:
            _set_schema_oauth_config(oauth_config)
        if keys is not ...:
            _set_oauth_keys(keys)
        if feature is not ...:
            _set_oauth_feature(feature)

    yield configure

    # restore exactly what the seed had, so the shared demo tenant is untouched
    session.execute(
        text(
            "UPDATE public.schema_config SET configuracao = CAST(:value AS jsonb) "
            "WHERE schema_name = 'demo'"
        ),
        {"value": json.dumps(original_config) if original_config else None},
    )
    session.execute(
        text("DELETE FROM demo.memoria WHERE tipo = :kind"),
        {"kind": MemoryEnum.OAUTH_KEYS.value},
    )
    session.execute(
        text(
            "UPDATE demo.memoria SET valor = CAST(:value AS json) WHERE tipo = 'features'"
        ),
        {"value": json.dumps(original_features) if original_features else "[]"},
    )
    session_commit()


def _post_auth_provider(client, code, schema="demo", **extra):
    return client.post(
        "/auth-provider", json={"schema": schema, "code": code, **extra}
    )


# --- GET /auth-provider/<schema> -------------------------------------------


def test_provider_config_is_published_for_a_configured_tenant(client, oauth_tenant):
    """The tenant's OAUTH settings reach the frontend, redirect_uri included"""
    response = client.get("/auth-provider/demo")

    assert response.status_code == status.HTTP_200_OK

    data = json.loads(response.data)["data"]

    assert data["clientId"] == CLIENT_ID
    assert data["loginUrl"] == LOGIN_URL
    assert data["company"] == "Hospital Teste"
    # the callback URL is derived server-side and appended to the authorize URL
    assert data["redirectUri"].endswith("/login-callback/demo")
    assert "redirect_uri=" in data["url"]
    # defaults for the optional settings this tenant did not set
    assert data["flow"] == "implicit"
    assert data["nonce"] is False
    assert data["state"] is False
    assert data["codeChallengeMethod"] is None


def test_provider_config_reports_the_configured_flow(client, oauth_tenant):
    """A tenant on the two-legged flow advertises it, along with its PKCE method"""
    oauth_tenant(
        oauth_config=_oauth_config(
            flow="authentication_basic",
            code_challenge_method="S256",
            nonce=True,
            state=True,
        )
    )

    data = json.loads(client.get("/auth-provider/demo").data)["data"]

    assert data["flow"] == "authentication_basic"
    assert data["codeChallengeMethod"] == "S256"
    assert data["nonce"] is True
    assert data["state"] is True


def test_provider_config_is_absent_for_a_tenant_without_oauth(client, oauth_tenant):
    """A tenant with no oauth block has no provider to redirect to"""
    oauth_tenant(oauth_config=None)

    assert client.get("/auth-provider/demo").status_code == status.HTTP_404_NOT_FOUND


# --- POST /auth-provider: the happy path ----------------------------------


def test_provider_login_issues_a_session(client, oauth_tenant, rsa_key_pair):
    """A validly signed id_token logs the mapped user in"""
    private_key, _ = rsa_key_pair

    response = _post_auth_provider(client, _make_token(private_key))

    assert response.status_code == status.HTTP_200_OK

    data = json.loads(response.data)["data"]

    assert data["email"] == DEMO_EMAIL
    assert data["schema"] == "demo"
    assert data["access_token"]
    # the OAUTH flag drives the frontend's logout redirect
    assert data["oauth"] is True
    assert data["logoutUrl"].endswith("/login/demo")
    # the refresh token is moved into a cookie by the route, never the body
    assert "refresh_token" not in data


def test_provider_login_reads_the_configured_claim_names(
    client, oauth_tenant, rsa_key_pair
):
    """The e-mail and name claims are read from the attributes the tenant configured"""
    private_key, _ = rsa_key_pair
    oauth_tenant(
        oauth_config=_oauth_config(email_attr="upn", name_attr="displayName")
    )

    token = _make_token(
        private_key,
        claims={"email": None, "upn": DEMO_EMAIL, "displayName": "Fulano Beltrano"},
    )

    response = _post_auth_provider(client, token)

    assert response.status_code == status.HTTP_200_OK
    assert json.loads(response.data)["data"]["email"] == DEMO_EMAIL


def test_provider_login_accepts_a_mixed_case_email_claim(
    client, oauth_tenant, rsa_key_pair
):
    """The provider's casing does not have to match the stored e-mail"""
    private_key, _ = rsa_key_pair

    response = _post_auth_provider(
        client, _make_token(private_key, claims={"email": DEMO_EMAIL.upper()})
    )

    assert response.status_code == status.HTTP_200_OK


def test_provider_login_works_for_a_token_without_a_name_claim(
    client, oauth_tenant, rsa_key_pair
):
    """A missing name claim falls back to a placeholder instead of failing"""
    private_key, _ = rsa_key_pair

    token = _make_token(private_key, claims={"name": None})
    # drop the key entirely rather than sending it as null
    payload = jwt.decode(token, options={"verify_signature": False})
    del payload["name"]
    token = jwt.encode(
        payload, key=private_key, algorithm="RS256", headers={"kid": KEY_ID}
    )

    assert _post_auth_provider(client, token).status_code == status.HTTP_200_OK


# --- POST /auth-provider: request validation ------------------------------


@pytest.mark.parametrize(
    "payload",
    [{}, {"schema": "demo"}, {"code": "abc"}],
    ids=["empty", "no-code", "no-schema"],
)
def test_provider_login_requires_schema_and_code(client, payload):
    """Both the tenant and the token are mandatory"""
    response = client.post("/auth-provider", json=payload)

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_provider_login_rejects_a_non_string_token(client, oauth_tenant):
    """A token that is not a string is refused before any parsing is attempted"""
    response = _post_auth_provider(client, {"not": "a token"})

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert "invalid token format" in json.loads(response.data)["message"]


def test_provider_login_is_refused_for_a_tenant_without_oauth(client, oauth_tenant):
    """A tenant that never configured OAUTH cannot be logged into through it"""
    oauth_tenant(oauth_config=None)

    response = _post_auth_provider(client, "any-token")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert "OAUTH não configurado" in json.loads(response.data)["message"]


def test_provider_login_needs_the_published_keys(client, oauth_tenant, rsa_key_pair):
    """Without a JWK set there is nothing to verify the signature against"""
    private_key, _ = rsa_key_pair
    oauth_tenant(keys=None)

    response = _post_auth_provider(client, _make_token(private_key))

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert "OAUTH KEYS não configurado" in json.loads(response.data)["message"]


# --- POST /auth-provider: token verification ------------------------------


def test_provider_login_rejects_an_unsupported_algorithm(client, oauth_tenant):
    """Only RSA signatures are accepted, so an HMAC token never reaches decode

    This is the check that stops a caller from re-signing a token with the
    (public, published) key material as an HMAC secret.
    """
    token = jwt.encode(
        {"aud": CLIENT_ID, "email": DEMO_EMAIL},
        key="not-a-real-secret",
        algorithm="HS256",
        headers={"kid": KEY_ID},
    )

    response = _post_auth_provider(client, token)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert "unsupported algorithm" in json.loads(response.data)["message"]


def test_provider_login_rejects_an_unknown_key_id(client, oauth_tenant, rsa_key_pair):
    """A token signed by a key the tenant did not publish is refused"""
    private_key, _ = rsa_key_pair

    response = _post_auth_provider(
        client, _make_token(private_key, headers={"kid": "some-other-key"})
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert "public key not found" in json.loads(response.data)["message"]


def test_provider_login_rejects_a_foreign_signature(client, oauth_tenant):
    """A token signed by a different key of the same kid fails verification"""
    impostor_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    response = _post_auth_provider(client, _make_token(impostor_key))

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert "decode error" in json.loads(response.data)["message"]


def test_provider_login_rejects_a_token_for_another_audience(
    client, oauth_tenant, rsa_key_pair
):
    """A token minted for a different client_id is not accepted"""
    private_key, _ = rsa_key_pair

    response = _post_auth_provider(
        client, _make_token(private_key, claims={"aud": "someone-elses-client"})
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert "decode error" in json.loads(response.data)["message"]


def test_provider_login_rejects_an_expired_token(client, oauth_tenant, rsa_key_pair):
    """An expired id_token cannot be replayed"""
    private_key, _ = rsa_key_pair
    expired = {
        "exp": datetime.now(timezone.utc) - timedelta(minutes=5),
        "iat": datetime.now(timezone.utc) - timedelta(minutes=10),
    }

    response = _post_auth_provider(client, _make_token(private_key, claims=expired))

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert "decode error" in json.loads(response.data)["message"]


def test_provider_login_rejects_a_malformed_token(client, oauth_tenant):
    """A string that is not a JWT at all is refused"""
    response = _post_auth_provider(client, "not.a.jwt")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


# --- POST /auth-provider: nonce ------------------------------------------


def test_provider_login_requires_a_nonce_when_the_tenant_asks_for_one(
    client, oauth_tenant, rsa_key_pair
):
    """A nonce-enabled tenant refuses a login that does not carry one"""
    private_key, _ = rsa_key_pair
    oauth_tenant(oauth_config=_oauth_config(nonce=True))

    response = _post_auth_provider(client, _make_token(private_key))

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert "Nonce não fornecido" in json.loads(response.data)["message"]


def test_provider_login_rejects_a_nonce_that_does_not_match_the_token(
    client, oauth_tenant, rsa_key_pair
):
    """The nonce in the token must be the one the frontend sent"""
    private_key, _ = rsa_key_pair
    oauth_tenant(oauth_config=_oauth_config(nonce=True))

    token = _make_token(private_key, claims={"nonce": str(uuid.uuid4())})

    response = _post_auth_provider(client, token, nonce=str(uuid.uuid4()))

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert "invalid nonce" in json.loads(response.data)["message"]


def test_provider_login_accepts_a_matching_nonce(client, oauth_tenant, rsa_key_pair):
    """A nonce that round-trips through the provider completes the login"""
    private_key, _ = rsa_key_pair
    oauth_tenant(oauth_config=_oauth_config(nonce=True))

    nonce = str(uuid.uuid4())
    token = _make_token(private_key, claims={"nonce": nonce})

    response = _post_auth_provider(client, token, nonce=nonce)

    assert response.status_code == status.HTTP_200_OK


# --- POST /auth-provider: user mapping and feature gate -------------------


def test_provider_login_requires_an_email_claim(client, oauth_tenant, rsa_key_pair):
    """A token whose configured e-mail attribute is null cannot be mapped"""
    private_key, _ = rsa_key_pair

    response = _post_auth_provider(
        client, _make_token(private_key, claims={"email": None})
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert "email inválido" in json.loads(response.data)["message"]


def test_provider_login_does_not_create_accounts(client, oauth_tenant, rsa_key_pair):
    """An e-mail with no NoHarm user is refused — OAUTH never provisions users"""
    private_key, _ = rsa_key_pair

    response = _post_auth_provider(
        client, _make_token(private_key, claims={"email": "ciclano@example.com"})
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert "cadastrado previamente" in json.loads(response.data)["message"]


def test_provider_login_is_blocked_without_the_oauth_feature(
    client, oauth_tenant, rsa_key_pair
):
    """A verified token still needs the tenant to have OAUTH enabled"""
    private_key, _ = rsa_key_pair
    oauth_tenant(feature=False)

    response = _post_auth_provider(client, _make_token(private_key))

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert "OAUTH bloqueado" in json.loads(response.data)["message"]


# --- POST /auth-provider: the authentication_basic flow -------------------


def test_basic_flow_exchanges_the_code_before_verifying(
    client, oauth_tenant, rsa_key_pair
):
    """On the two-legged flow the authorization code is swapped for an id_token"""
    private_key, _ = rsa_key_pair
    oauth_tenant(oauth_config=_oauth_config(flow="authentication_basic"))

    provider_response = MagicMock(status_code=status.HTTP_200_OK)
    provider_response.json.return_value = {"id_token": _make_token(private_key)}

    with patch(
        "services.auth_service.requests.post", return_value=provider_response
    ) as post:
        response = _post_auth_provider(client, "an-authorization-code")

    assert response.status_code == status.HTTP_200_OK

    # the code is exchanged at the token endpoint, authenticated with the client secret
    _, kwargs = post.call_args
    assert kwargs["url"] == LOGIN_URL
    assert kwargs["auth"] == (CLIENT_ID, CLIENT_SECRET)
    assert kwargs["data"]["grant_type"] == "authorization_code"
    assert kwargs["data"]["code"] == "an-authorization-code"
    assert kwargs["data"]["redirect_uri"].endswith("/login-callback/demo")


def test_basic_flow_surfaces_a_provider_error(client, oauth_tenant):
    """A non-200 from the token endpoint ends the login"""
    oauth_tenant(oauth_config=_oauth_config(flow="authentication_basic"))

    with patch(
        "services.auth_service.requests.post",
        return_value=MagicMock(status_code=status.HTTP_400_BAD_REQUEST),
    ):
        response = _post_auth_provider(client, "an-authorization-code")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert "OAUTH provider error" in json.loads(response.data)["message"]
