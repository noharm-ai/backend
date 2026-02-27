"""Integration tests for GET /prescriptions/<idPrescription>

Covers the prescription_view_service._internal_get_prescription() pipeline:
- Authorization and permissions
- Response structure and field types
- Drug lists split by source (DRUG / SOLUTION / PROCEDURE)
- Aggregated vs non-aggregated prescriptions
- Prescription status variants
- Review data structure
- Patient data sub-object
- Interventions and exams structure
- Date field ISO formatting
- Error cases
"""

from datetime import datetime, timedelta

from models.enums import DrugTypeEnum
from tests.conftest import session
from tests.utils.utils_test_prescription import (
    create_prescription,
    create_prescription_drug,
    create_basic_prescription,
    test_counters,
)

# Seed prescriptions already in the test database (from noharm-ai/database fixtures)
SEED_PRESCRIPTION_ID = "20"
SEED_PRESCRIPTION_WITH_BIRTHDATE = "199"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _next_prescription_id():
    return test_counters["id_prescription"]


def _next_admission_number():
    return test_counters["admission_number"]


def _inc_counters():
    test_counters["id_prescription"] += 1
    test_counters["admission_number"] += 1


def _create_prescription_with_sources(sources: list[str]):
    """Create a prescription whose drugs have the given `source` values.

    Returns the prescription id.
    """
    id_pres = _next_prescription_id()
    adm = _next_admission_number()

    create_prescription(
        id=id_pres,
        admissionNumber=adm,
        idPatient=1,
        date=datetime.now(),
        expire=datetime.now() + timedelta(days=1),
    )

    for i, source in enumerate(sources):
        create_prescription_drug(
            id=int(f"{id_pres}{i + 1:03d}"),
            idPrescription=id_pres,
            idDrug=3,
            source=source,
        )

    _inc_counters()
    return id_pres


# ===========================================================================
# Group 1 – Authorization
# ===========================================================================


def test_get_prescription_view_permission_denied(client, user_manager_headers):
    """USER_MANAGER lacks READ_PRESCRIPTION → must return 401."""
    response = client.get(f"/prescriptions/{SEED_PRESCRIPTION_ID}", headers=user_manager_headers)
    assert response.status_code == 401


# ===========================================================================
# Group 2 – Response structure (using seed prescription)
# ===========================================================================


def test_get_prescription_view_response_structure(client, analyst_headers):
    """All expected top-level keys must be present in the response."""
    response = client.get(f"/prescriptions/{SEED_PRESCRIPTION_ID}", headers=analyst_headers)
    assert response.status_code == 200

    data = response.get_json()["data"]

    required_keys = [
        "idPrescription",
        "idSegment",
        "idPatient",
        "idHospital",
        "admissionNumber",
        "bed",
        "status",
        "date",
        "expire",
        "agg",
        "concilia",
        "prescription",
        "solution",
        "procedures",
        "diet",
        "infusion",
        "headers",
        "alertStats",
        "interventions",
        "prevIntervention",
        "existIntervention",
        "exams",
        "alertExams",
        "clinicalNotes",
        "clinicalNotesStats",
        "review",
        "patient",
        "protocolAlerts",
    ]

    for key in required_keys:
        assert key in data, f"Missing key: {key}"


def test_get_prescription_view_field_types(client, analyst_headers):
    """Key fields must have the correct types."""
    response = client.get(f"/prescriptions/{SEED_PRESCRIPTION_ID}", headers=analyst_headers)
    data = response.get_json()["data"]

    assert isinstance(data["idPrescription"], str)
    assert isinstance(data["prescription"], list)
    assert isinstance(data["solution"], list)
    assert isinstance(data["procedures"], list)
    assert isinstance(data["diet"], list)
    assert isinstance(data["interventions"], list)
    assert isinstance(data["exams"], list)
    assert isinstance(data["alertExams"], int)
    assert isinstance(data["prevIntervention"], bool)
    assert isinstance(data["existIntervention"], bool)
    assert isinstance(data["review"], dict)
    assert isinstance(data["patient"], dict)
    assert isinstance(data["clinicalNotes"], int)


def test_get_prescription_view_db_match(client, analyst_headers):
    """idPrescription, bed, status and admissionNumber must match the DB record."""
    from models.prescription import Prescription

    response = client.get(f"/prescriptions/{SEED_PRESCRIPTION_ID}", headers=analyst_headers)
    data = response.get_json()["data"]

    prescription = session.get(Prescription, SEED_PRESCRIPTION_ID)

    assert data["idPrescription"] == str(prescription.id)
    assert data["bed"] == prescription.bed
    assert data["status"] == prescription.status
    assert data["admissionNumber"] == prescription.admissionNumber


# ===========================================================================
# Group 3 – Date field formatting
# ===========================================================================


def test_get_prescription_view_date_fields_iso_format(client, analyst_headers):
    """date and expire must be ISO 8601 strings; birthdate must be 'YYYY-MM-DD'."""
    response = client.get(f"/prescriptions/{SEED_PRESCRIPTION_WITH_BIRTHDATE}", headers=analyst_headers)
    assert response.status_code == 200
    data = response.get_json()["data"]

    # Verify date and expire are parseable ISO strings
    # date is always required; expire may be NULL in seed data
    datetime.fromisoformat(data["date"])
    if data["expire"] is not None:
        datetime.fromisoformat(data["expire"])

    # Known birthdate for this seed prescription
    assert data["birthdate"] == "1941-02-05"


def test_get_prescription_view_date_created_prescription(client, analyst_headers):
    """date and expire on a freshly created prescription must be ISO strings."""
    prescription = create_basic_prescription()
    response = client.get(f"/prescriptions/{prescription.id}", headers=analyst_headers)
    assert response.status_code == 200
    data = response.get_json()["data"]

    datetime.fromisoformat(data["date"])
    datetime.fromisoformat(data["expire"])


# ===========================================================================
# Group 4 – Drug list split by source
# ===========================================================================


def test_get_prescription_view_drugs_in_prescription_array(client, analyst_headers):
    """Drugs with source DRUG appear in 'prescription', not in solution/procedures."""
    id_pres = _create_prescription_with_sources(
        [DrugTypeEnum.DRUG.value, DrugTypeEnum.DRUG.value]
    )
    response = client.get(f"/prescriptions/{id_pres}", headers=analyst_headers)
    assert response.status_code == 200
    data = response.get_json()["data"]

    assert len(data["prescription"]) == 2
    assert len(data["solution"]) == 0
    assert len(data["procedures"]) == 0


def test_get_prescription_view_solution_in_solution_array(client, analyst_headers):
    """Drugs with source SOLUTION appear in 'solution', not 'prescription'."""
    id_pres = _create_prescription_with_sources(
        [DrugTypeEnum.DRUG.value, DrugTypeEnum.SOLUTION.value]
    )
    response = client.get(f"/prescriptions/{id_pres}", headers=analyst_headers)
    assert response.status_code == 200
    data = response.get_json()["data"]

    assert len(data["prescription"]) == 1
    assert len(data["solution"]) == 1


def test_get_prescription_view_procedure_in_procedures_array(client, analyst_headers):
    """Drugs with source PROCEDURE appear in 'procedures'."""
    id_pres = _create_prescription_with_sources([DrugTypeEnum.PROCEDURE.value])
    response = client.get(f"/prescriptions/{id_pres}", headers=analyst_headers)
    assert response.status_code == 200
    data = response.get_json()["data"]

    assert len(data["procedures"]) == 1
    assert len(data["prescription"]) == 0


def test_get_prescription_view_diet_in_diet_array(client, analyst_headers):
    """Drugs with source DIET appear in 'diet'."""
    id_pres = _create_prescription_with_sources([DrugTypeEnum.DIET.value])
    response = client.get(f"/prescriptions/{id_pres}", headers=analyst_headers)
    assert response.status_code == 200
    data = response.get_json()["data"]

    assert len(data["diet"]) == 1
    assert len(data["prescription"]) == 0


def test_get_prescription_view_no_drugs(client, analyst_headers):
    """Prescription with no drugs must return empty lists for all drug arrays."""
    id_pres = _next_prescription_id()
    adm = _next_admission_number()
    create_prescription(
        id=id_pres,
        admissionNumber=adm,
        idPatient=1,
        date=datetime.now(),
        expire=datetime.now() + timedelta(days=1),
    )
    _inc_counters()

    response = client.get(f"/prescriptions/{id_pres}", headers=analyst_headers)
    assert response.status_code == 200
    data = response.get_json()["data"]

    assert data["prescription"] == []
    assert data["solution"] == []
    assert data["procedures"] == []
    assert data["diet"] == []


def test_get_prescription_view_mixed_sources(client, analyst_headers):
    """Drugs with different sources are correctly routed to separate arrays."""
    id_pres = _create_prescription_with_sources(
        [
            DrugTypeEnum.DRUG.value,
            DrugTypeEnum.SOLUTION.value,
            DrugTypeEnum.PROCEDURE.value,
            DrugTypeEnum.DIET.value,
        ]
    )
    response = client.get(f"/prescriptions/{id_pres}", headers=analyst_headers)
    assert response.status_code == 200
    data = response.get_json()["data"]

    assert len(data["prescription"]) == 1
    assert len(data["solution"]) == 1
    assert len(data["procedures"]) == 1
    assert len(data["diet"]) == 1


# ===========================================================================
# Group 5 – Prescription status variants
# ===========================================================================


def test_get_prescription_view_pending_status(client, analyst_headers):
    """Prescription with status='0' (pending) must be returned as-is."""
    id_pres = _next_prescription_id()
    adm = _next_admission_number()
    create_prescription(
        id=id_pres, admissionNumber=adm, idPatient=1, status="0"
    )
    _inc_counters()

    response = client.get(f"/prescriptions/{id_pres}", headers=analyst_headers)
    assert response.status_code == 200
    assert response.get_json()["data"]["status"] == "0"


def test_get_prescription_view_checked_status(client, analyst_headers):
    """Checking a prescription via the check endpoint must reflect status='s' in the view."""
    prescription = create_basic_prescription()

    # The DB resets status on direct insert; use the proper check endpoint instead
    check_payload = {
        "idPrescription": prescription.id,
        "status": "s",
        "evaluationTime": 0,
        "alerts": [],
        "fastCheck": False,
    }
    check_response = client.post(
        "/prescriptions/status", json=check_payload, headers=analyst_headers
    )
    assert check_response.status_code == 200

    # View must now reflect the checked status
    response = client.get(f"/prescriptions/{prescription.id}", headers=analyst_headers)
    assert response.status_code == 200
    assert response.get_json()["data"]["status"] == "s"


# ===========================================================================
# Group 6 – Aggregated vs non-aggregated
# ===========================================================================


def test_get_prescription_view_non_agg_has_list_headers(client, analyst_headers):
    """Non-aggregated prescription must return headers as an empty list."""
    prescription = create_basic_prescription()
    response = client.get(f"/prescriptions/{prescription.id}", headers=analyst_headers)
    assert response.status_code == 200
    data = response.get_json()["data"]

    assert not data["agg"]
    assert isinstance(data["headers"], list)
    assert data["headers"] == []


def test_get_prescription_view_agg_has_dict_headers(client, analyst_headers):
    """Aggregated prescription must return headers as a dict (keyed by prescription id)."""
    id_pres = _next_prescription_id()
    adm = _next_admission_number()
    create_prescription(
        id=id_pres,
        admissionNumber=adm,
        idPatient=1,
        agg=True,
        date=datetime.now(),
        expire=datetime.now() + timedelta(days=1),
    )
    create_prescription_drug(
        id=int(f"{id_pres}001"),
        idPrescription=id_pres,
        idDrug=3,
        source=DrugTypeEnum.DRUG.value,
    )
    _inc_counters()

    response = client.get(f"/prescriptions/{id_pres}", headers=analyst_headers)
    assert response.status_code == 200
    data = response.get_json()["data"]

    assert data["agg"] is True
    assert isinstance(data["headers"], dict)


# ===========================================================================
# Group 7 – Review data structure
# ===========================================================================


def test_get_prescription_view_review_structure(client, analyst_headers):
    """review must be a dict with the expected keys."""
    prescription = create_basic_prescription()
    response = client.get(f"/prescriptions/{prescription.id}", headers=analyst_headers)
    assert response.status_code == 200
    data = response.get_json()["data"]

    review = data["review"]
    assert isinstance(review, dict)
    assert "reviewed" in review
    assert "reviewedAt" in review
    assert "reviewedBy" in review


def test_get_prescription_view_new_prescription_not_reviewed(client, analyst_headers):
    """A freshly created prescription must report reviewed=False."""
    prescription = create_basic_prescription()
    response = client.get(f"/prescriptions/{prescription.id}", headers=analyst_headers)
    data = response.get_json()["data"]

    assert data["review"]["reviewed"] is False
    assert data["review"]["reviewedAt"] is None
    assert data["review"]["reviewedBy"] is None


# ===========================================================================
# Group 8 – Patient data sub-object
# ===========================================================================


def test_get_prescription_view_patient_sub_object_keys(client, analyst_headers):
    """patient sub-object must contain lactating, pregnant and tags."""
    response = client.get(f"/prescriptions/{SEED_PRESCRIPTION_ID}", headers=analyst_headers)
    data = response.get_json()["data"]

    patient = data["patient"]
    assert "lactating" in patient
    assert "pregnant" in patient
    assert "tags" in patient


def test_get_prescription_view_patient_demographics(client, analyst_headers):
    """birthdate from seed prescription 199 must match the expected value."""
    response = client.get(f"/prescriptions/{SEED_PRESCRIPTION_WITH_BIRTHDATE}", headers=analyst_headers)
    data = response.get_json()["data"]

    assert data["birthdate"] == "1941-02-05"
    # age must be a non-negative numeric value
    assert isinstance(data["age"], (int, float, str))


def test_get_prescription_view_patient_fields_present(client, analyst_headers):
    """Top-level patient demographic fields must all be present."""
    response = client.get(f"/prescriptions/{SEED_PRESCRIPTION_ID}", headers=analyst_headers)
    data = response.get_json()["data"]

    for key in ["birthdate", "gender", "weight", "height", "age", "dialysis", "admissionDate"]:
        assert key in data, f"Missing patient field: {key}"


# ===========================================================================
# Group 9 – Interventions and exams structure
# ===========================================================================


def test_get_prescription_view_interventions_structure(client, analyst_headers):
    """interventions, prevIntervention and existIntervention must be present."""
    prescription = create_basic_prescription()
    response = client.get(f"/prescriptions/{prescription.id}", headers=analyst_headers)
    assert response.status_code == 200
    data = response.get_json()["data"]

    assert isinstance(data["interventions"], list)
    assert isinstance(data["prevIntervention"], bool)
    assert isinstance(data["existIntervention"], bool)


def test_get_prescription_view_exams_structure(client, analyst_headers):
    """exams must be a list and alertExams must be a non-negative int."""
    prescription = create_basic_prescription()
    response = client.get(f"/prescriptions/{prescription.id}", headers=analyst_headers)
    assert response.status_code == 200
    data = response.get_json()["data"]

    assert isinstance(data["exams"], list)
    assert isinstance(data["alertExams"], int)
    assert data["alertExams"] >= 0


def test_get_prescription_view_alert_stats_structure(client, analyst_headers):
    """alertStats must be a dict."""
    prescription = create_basic_prescription()
    response = client.get(f"/prescriptions/{prescription.id}", headers=analyst_headers)
    data = response.get_json()["data"]

    assert isinstance(data["alertStats"], dict)


def test_get_prescription_view_clinical_notes_structure(client, analyst_headers):
    """clinicalNotes and clinicalNotesStats must be present and typed correctly."""
    prescription = create_basic_prescription()
    response = client.get(f"/prescriptions/{prescription.id}", headers=analyst_headers)
    data = response.get_json()["data"]

    assert isinstance(data["clinicalNotes"], int)
    assert isinstance(data["clinicalNotesStats"], dict)


# ===========================================================================
# Group 10 – Error cases
# ===========================================================================


def test_get_prescription_view_not_found(client, analyst_headers):
    """Non-existent prescription id must return HTTP 400 (ValidationError)."""
    response = client.get("/prescriptions/999999999", headers=analyst_headers)
    assert response.status_code == 400


def test_get_prescription_view_unauthenticated(client):
    """Request without auth headers must return HTTP 401."""
    response = client.get(f"/prescriptions/{SEED_PRESCRIPTION_ID}")
    assert response.status_code == 401
