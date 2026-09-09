"""Tests: PEP deep link (GET /prescriptions/pep-link)

The endpoint hands the frontend a link back into the client's own electronic
patient record (PEP). The template lives in the tenant's schema_config and
carries three placeholders, which the service fills from the caller and from
the prescription:

- ``{USER_EXTERNAL_ID}``: the caller's id in the client's own system
- ``{ADMISSION_NUMBER}``: the prescription's admission
- ``{FKHOSPITAL}``: the prescription's hospital

Every piece has to be configured for a link to come back, so the tests below
cover the happy path plus each missing-configuration branch.
"""

import pytest

from models.appendix import SchemaConfig
from models.main import User
from security.role import Role
from tests.conftest import get_access, make_headers, session, session_commit
from tests.utils.utils_test_prescription import create_basic_prescription

URL = "/prescriptions/pep-link"

# the schema and the user behind tests.conftest.get_access defaults
SCHEMA = "demo"
DEMO_USER_ID = 1

# stands in for the caller's id inside the client's own system
EXTERNAL_ID = "ZZTEST-PEP-EXTERNAL"

PEP_TEMPLATE = (
    "https://pep.example.com/atendimento"
    "?usuario={USER_EXTERNAL_ID}&atendimento={ADMISSION_NUMBER}&hospital={FKHOSPITAL}"
)


def _set_schema_config(config):
    """Replace the tenant's schema_config payload"""
    session.query(SchemaConfig).filter(SchemaConfig.schemaName == SCHEMA).update(
        {"config": config}, synchronize_session=False
    )
    session_commit()


def _set_user_external(external):
    """Set (or clear) the caller's external id"""
    session.query(User).filter(User.id == DEMO_USER_ID).update(
        {"external": external}, synchronize_session=False
    )
    session_commit()


@pytest.fixture(autouse=True)
def restore_pep_setup():
    """Snapshot the schema config and the caller's external id, then restore them.

    Both are seed-level records shared with every other test, so each test here
    puts them back exactly as it found them.
    """
    original_config = (
        session.query(SchemaConfig)
        .filter(SchemaConfig.schemaName == SCHEMA)
        .first()
        .config
    )
    original_external = session.query(User).filter(User.id == DEMO_USER_ID).first().external

    # the setup a configured tenant has; individual tests narrow it down
    _set_schema_config({"pepLink": PEP_TEMPLATE})
    _set_user_external(EXTERNAL_ID)

    yield

    _set_schema_config(original_config)
    _set_user_external(original_external)


def test_pep_link_fills_every_placeholder(client, analyst_headers):
    """GET /prescriptions/pep-link - substitui usuário, atendimento e hospital no template"""
    prescription = create_basic_prescription()

    response = client.get(
        URL, query_string={"idPrescription": prescription.id}, headers=analyst_headers
    )

    assert response.status_code == 200
    assert response.get_json()["data"]["pepLink"] == (
        "https://pep.example.com/atendimento"
        f"?usuario={EXTERNAL_ID}"
        f"&atendimento={prescription.admissionNumber}"
        f"&hospital={prescription.idHospital}"
    )


def test_pep_link_replaces_repeated_placeholders(client, analyst_headers):
    """A placeholder used twice in the template is filled at both positions"""
    prescription = create_basic_prescription()
    _set_schema_config(
        {"pepLink": "https://pep.example.com/{ADMISSION_NUMBER}/x/{ADMISSION_NUMBER}"}
    )

    response = client.get(
        URL, query_string={"idPrescription": prescription.id}, headers=analyst_headers
    )

    assert response.status_code == 200

    admission = prescription.admissionNumber
    assert (
        response.get_json()["data"]["pepLink"]
        == f"https://pep.example.com/{admission}/x/{admission}"
    )


def test_pep_link_keeps_a_template_without_placeholders(client, analyst_headers):
    """A template with nothing to substitute comes back verbatim"""
    prescription = create_basic_prescription()
    _set_schema_config({"pepLink": "https://pep.example.com/home"})

    response = client.get(
        URL, query_string={"idPrescription": prescription.id}, headers=analyst_headers
    )

    assert response.status_code == 200
    assert response.get_json()["data"]["pepLink"] == "https://pep.example.com/home"


def test_pep_link_rejects_unknown_prescription(client, analyst_headers):
    """An id with no prescription behind it is a validation error"""
    response = client.get(
        URL, query_string={"idPrescription": 100999999}, headers=analyst_headers
    )

    assert response.status_code == 400
    assert response.get_json()["code"] == "errors.businessRules"


def test_pep_link_requires_the_prescription_param(client, analyst_headers):
    """Calling without idPrescription is rejected instead of returning a broken link"""
    response = client.get(URL, headers=analyst_headers)

    assert response.status_code == 400
    assert response.get_json()["code"] == "errors.businessRules"


def test_pep_link_requires_the_user_external_id(client, analyst_headers):
    """A caller with no external id cannot be identified to the PEP"""
    prescription = create_basic_prescription()
    _set_user_external(None)

    response = client.get(
        URL, query_string={"idPrescription": prescription.id}, headers=analyst_headers
    )

    assert response.status_code == 400
    assert response.get_json()["code"] == "errors.businessRules"


def test_pep_link_requires_a_configured_schema(client, analyst_headers):
    """A tenant whose schema_config carries no pepLink gets a validation error"""
    prescription = create_basic_prescription()
    _set_schema_config({})

    response = client.get(
        URL, query_string={"idPrescription": prescription.id}, headers=analyst_headers
    )

    assert response.status_code == 400
    assert response.get_json()["code"] == "errors.businessRules"


def test_pep_link_requires_read_prescription_permission(client):
    """A DISPENSING_MANAGER holds no READ_PRESCRIPTION, so the link is denied"""
    prescription = create_basic_prescription()
    headers = make_headers(get_access(client, roles=[Role.DISPENSING_MANAGER.value]))

    response = client.get(
        URL, query_string={"idPrescription": prescription.id}, headers=headers
    )

    assert response.status_code == 401
