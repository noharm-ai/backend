"""Integration tests for the regulation branch of GET /prescriptions/search
(``prescription_service.search``).

The fast search box is the single entry point the user types an id into, and it
answers with more than prescriptions: a regulation ("regulação") solicitation
carrying that id is returned alongside them, tagged ``type = "regulation"`` and
carrying ``idRegSolicitation`` so the frontend can route to the regulation
screen instead of the prescription screen.

That branch is gated twice -- the caller must hold READ_REGULATION *and* the
schema must have the REGULATION feature enabled -- and
``tests/integration/test_prescription_search.py`` notes it is left uncovered
there, because the demo schema ships without regulation configuration. These
tests turn the feature on for the duration of the test, seed a solicitation and
drive both gates, the payload the branch builds and how it mixes with the
prescription results.
"""

import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from models.enums import FeatureEnum
from security.role import Role
from tests.conftest import get_access, make_headers, session, session_commit
from tests.utils import utils_test_regulation as utils
from tests.utils.utils_test_prescription import create_prescription
from utils import status

SEARCH_URL = "/prescriptions/search"

# 901xxx block, inside the >= 900000 range utils_test_regulation reserves
TYPE_CONSULTATION = utils.TYPE_ID_BASE + 101

SOLICITATION_WITH_DEPARTMENT = utils.SOLICITATION_ID_BASE + 101
SOLICITATION_WITHOUT_DEPARTMENT = utils.SOLICITATION_ID_BASE + 102

ADMISSION_WITH_DEPARTMENT = utils.ADMISSION_BASE + 101
ADMISSION_WITHOUT_DEPARTMENT = utils.ADMISSION_BASE + 102

PATIENT_WITH_DEPARTMENT = utils.ADMISSION_BASE + 101
PATIENT_WITHOUT_DEPARTMENT = utils.ADMISSION_BASE + 102

SOLICITATION_DATE = datetime(2024, 5, 7, 10, 30, 0)
STAGE = 2

DEPARTMENT_ID = 1
DEPARTMENT_NAME = "Setor Adulto 1"
# never created as a department, so the outer join yields no name
ORPHAN_DEPARTMENT_ID = 987654

# a solicitation id that is also a prescription id, to prove both branches
# answer the same term
SHARED_ID = utils.SOLICITATION_ID_BASE + 103
SHARED_ADMISSION = utils.ADMISSION_BASE + 103
SHARED_PATIENT = utils.ADMISSION_BASE + 103


def _read_features():
    """Return the feature list currently stored in the demo schema."""
    row = session.execute(
        text("SELECT valor FROM demo.memoria WHERE tipo = 'features'")
    ).first()
    return list(row[0]) if row else []


def _write_features(features):
    """Overwrite the demo schema feature list."""
    session.execute(
        text(
            "UPDATE demo.memoria SET valor = CAST(:value AS json) WHERE tipo = 'features'"
        ),
        {"value": json.dumps(features)},
    )
    session_commit()


@pytest.fixture
def regulation_feature():
    """Enable REGULATION for the demo schema and restore it afterwards."""
    original = _read_features()
    _write_features(original + [FeatureEnum.REGULATION.value])
    yield
    _write_features(original)


@pytest.fixture
def no_regulation_feature():
    """Make sure REGULATION is *not* enabled for the demo schema."""
    original = _read_features()
    _write_features([f for f in original if f != FeatureEnum.REGULATION.value])
    yield
    _write_features(original)


@pytest.fixture
def solicitations():
    """Seed the solicitations the search is expected to find."""
    utils.clean_regulation_data()

    utils.create_solicitation_type(
        id=TYPE_CONSULTATION, name="ZZTEST Consulta busca", tp_type=1
    )

    for solicitation_id, admission, patient, department in (
        (
            SOLICITATION_WITH_DEPARTMENT,
            ADMISSION_WITH_DEPARTMENT,
            PATIENT_WITH_DEPARTMENT,
            DEPARTMENT_ID,
        ),
        (
            SOLICITATION_WITHOUT_DEPARTMENT,
            ADMISSION_WITHOUT_DEPARTMENT,
            PATIENT_WITHOUT_DEPARTMENT,
            ORPHAN_DEPARTMENT_ID,
        ),
    ):
        utils.create_patient(
            admission_number=admission,
            id_patient=patient,
            birthdate=datetime(1975, 2, 11),
            gender="F",
        )
        utils.create_solicitation(
            id=solicitation_id,
            admission_number=admission,
            id_patient=patient,
            date=SOLICITATION_DATE,
            id_reg_solicitation_type=TYPE_CONSULTATION,
            id_department=department,
            stage=STAGE,
        )

    yield

    utils.clean_regulation_data()


@pytest.fixture
def solicitation_sharing_prescription_id():
    """A solicitation and a prescription that answer to the very same term."""
    utils.clean_regulation_data()

    utils.create_solicitation_type(
        id=TYPE_CONSULTATION, name="ZZTEST Consulta busca", tp_type=1
    )
    utils.create_patient(
        admission_number=SHARED_ADMISSION,
        id_patient=SHARED_PATIENT,
        birthdate=datetime(1975, 2, 11),
        gender="F",
    )
    utils.create_solicitation(
        id=SHARED_ID,
        admission_number=SHARED_ADMISSION,
        id_patient=SHARED_PATIENT,
        date=SOLICITATION_DATE,
        id_reg_solicitation_type=TYPE_CONSULTATION,
        id_department=DEPARTMENT_ID,
        stage=STAGE,
    )
    # the prescription carries the same id; it is removed by clean_test_artifacts
    create_prescription(
        id=SHARED_ID,
        admissionNumber=SHARED_ADMISSION,
        idPatient=SHARED_PATIENT,
        date=datetime.now() - timedelta(hours=1),
        agg=True,
        status="0",
        idDepartment=DEPARTMENT_ID,
    )

    yield

    utils.clean_regulation_data()


def _search(client, headers, term):
    """Run the fast search and return the decoded result list."""
    response = client.get(f"{SEARCH_URL}?term={term}", headers=headers)

    assert response.status_code == status.HTTP_200_OK

    return response.get_json()["data"]


def _regulation_results(results):
    """Keep only the regulation entries of a search result."""
    return [item for item in results if item["type"] == "regulation"]


# --- the regulation payload ---------------------------------------------------


def test_search_finds_a_solicitation_by_id(
    client, regulator_headers, regulation_feature, solicitations
):
    """A solicitation id answers with the regulation entry the frontend routes on."""
    results = _search(client, regulator_headers, SOLICITATION_WITH_DEPARTMENT)

    assert results == [
        {
            "idPrescription": None,
            "idRegSolicitation": SOLICITATION_WITH_DEPARTMENT,
            "admissionNumber": ADMISSION_WITH_DEPARTMENT,
            "date": SOLICITATION_DATE.isoformat(),
            "status": STAGE,
            "agg": False,
            "concilia": False,
            "birthdate": None,
            "gender": None,
            "department": DEPARTMENT_NAME,
            "admissionDate": None,
            "type": "regulation",
        }
    ]


def test_search_keeps_a_solicitation_whose_department_is_unknown(
    client, regulator_headers, regulation_feature, solicitations
):
    """The department join is an outer join: a dangling id costs the name, not the row."""
    results = _search(client, regulator_headers, SOLICITATION_WITHOUT_DEPARTMENT)

    assert len(results) == 1
    assert results[0]["idRegSolicitation"] == SOLICITATION_WITHOUT_DEPARTMENT
    assert results[0]["department"] is None


def test_search_ignores_an_unknown_solicitation_id(
    client, regulator_headers, regulation_feature, solicitations
):
    """An id no solicitation carries answers with an empty list, not an error."""
    assert _search(client, regulator_headers, utils.SOLICITATION_ID_BASE + 999) == []


# --- the two gates ------------------------------------------------------------


def test_search_hides_solicitations_when_the_feature_is_off(
    client, regulator_headers, no_regulation_feature, solicitations
):
    """READ_REGULATION alone is not enough: the schema must enable REGULATION."""
    assert _search(client, regulator_headers, SOLICITATION_WITH_DEPARTMENT) == []


def test_search_hides_solicitations_from_a_caller_without_read_regulation(
    client, analyst_headers, regulation_feature, solicitations
):
    """The feature being on does not open the branch to a role that lacks the permission."""
    results = _search(client, analyst_headers, SOLICITATION_WITH_DEPARTMENT)

    assert _regulation_results(results) == []


def test_search_is_closed_to_a_caller_holding_none_of_the_permissions(
    client, regulation_feature, solicitations
):
    """SUPPORT_REQUESTER holds no search permission at all, so it is refused [401]."""
    headers = make_headers(
        get_access(client, roles=[Role.SUPPORT_REQUESTER.value])
    )

    response = client.get(
        f"{SEARCH_URL}?term={SOLICITATION_WITH_DEPARTMENT}", headers=headers
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_search_requires_authentication(client, regulation_feature, solicitations):
    """No token, no search [401]."""
    response = client.get(f"{SEARCH_URL}?term={SOLICITATION_WITH_DEPARTMENT}")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


# --- mixing with the prescription branch --------------------------------------


def test_search_returns_prescriptions_and_solicitations_for_the_same_term(
    client, admin_headers, regulation_feature, solicitation_sharing_prescription_id
):
    """A caller holding both permissions sees both kinds, each tagged by type."""
    results = _search(client, admin_headers, SHARED_ID)

    by_type = {item["type"] for item in results}
    assert by_type == {"prescription", "regulation"}

    regulation = _regulation_results(results)[0]
    assert regulation["idRegSolicitation"] == SHARED_ID
    assert regulation["idPrescription"] is None

    prescription = [item for item in results if item["type"] == "prescription"][0]
    assert prescription["idPrescription"] == str(SHARED_ID)
    # the prescription branch carries the patient data the regulation one omits
    assert prescription["admissionNumber"] == SHARED_ADMISSION


def test_search_without_a_term_is_rejected(
    client, regulator_headers, regulation_feature
):
    """The endpoint needs a term before it queries anything [400 BAD REQUEST]."""
    response = client.get(SEARCH_URL, headers=regulator_headers)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
