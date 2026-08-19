"""Integration tests for the navigation "copy patient" endpoint.

Covers ``navigation_service.copy_patient`` (POST /navigation/copy), which had
no coverage at all. The endpoint gathers the drugs of a patient's newest
aggregated prescription, encrypts the identifying data (name, phone and
clinical notes) and hands the whole payload to a backend Lambda that performs
the copy in the destination schema.

Only the Lambda call is mocked — the drug selection, the encryption and the
error handling all run for real against the test database. The payload the
service would have sent is captured from the mock and decrypted, so the tests
assert on what actually crosses the boundary.
"""

import base64
import io
import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text

from config import Config
from security.role import Role
from tests.conftest import get_access, make_headers, session, session_commit

URL = "/navigation/copy"

# Non-CPOE cohort (department 1 -> segment 1).
ADMISSION_STANDARD = 991001
# CPOE cohort (department 3 -> segment 2).
ADMISSION_CPOE = 991002
# Patient without any aggregated prescription.
ADMISSION_WITHOUT_AGG = 991003

_ADMISSIONS = (ADMISSION_STANDARD, ADMISSION_CPOE, ADMISSION_WITHOUT_AGG)

DEPARTMENT_STANDARD = 1
DEPARTMENT_CPOE = 3

AGG_DATE = datetime(2026, 1, 10, 12, 0)

# Prescription ids, and the prescription-drug ids they carry.
PRESC_AGG_STANDARD = 991100
PRESC_OLD_GROUP = 991101
PRESC_NEW_GROUP = 991102
PRESC_AGG_CPOE = 991200
PRESC_CPOE_A = 991201
PRESC_CPOE_B = 991202

DRUG_OLD_GROUP = 991101001
DRUG_NEW_GROUP = 991102001
DRUG_CPOE_A = 991201001
DRUG_CPOE_B = 991202001

BED = "301"
INSURANCE = "zztest-insurance"

PATIENT_NAME = "Zztest Paciente Navegação"
PATIENT_PHONE = "+55 51 90000-0000"


def _insert_patient(admission_number):
    """Insert a ``pessoa`` row keyed by the given admission number."""
    session.execute(
        text(
            "INSERT INTO demo.pessoa "
            "(fkhospital, fkpessoa, nratendimento, dtnascimento, dtinternacao) "
            "VALUES (1, :admission, :admission, :birthdate, :admitted)"
        ),
        {
            "admission": admission_number,
            "birthdate": datetime(1975, 5, 5),
            "admitted": datetime(2026, 1, 1),
        },
    )


def _insert_prescription(
    id_prescription, admission_number, id_department, date, expire, agg=None
):
    """Insert a ``prescricao`` row.

    ``idsegmento`` is left to the insert trigger, which derives it from the
    department through ``demo.segmentosetor``.
    """
    session.execute(
        text(
            "INSERT INTO demo.prescricao "
            "(fkhospital, fksetor, fkprescricao, fkpessoa, nratendimento, "
            "dtprescricao, dtvigencia, agregada, status, leito, convenio) "
            "VALUES (1, :department, :id, :admission, :admission, :date, "
            ":expire, :agg, '0', :bed, :insurance)"
        ),
        {
            "id": id_prescription,
            "admission": admission_number,
            "department": id_department,
            "date": date,
            "expire": expire,
            "agg": agg,
            "bed": BED,
            "insurance": INSURANCE,
        },
    )


def _insert_prescription_drug(id_prescription_drug, id_prescription, id_drug):
    """Insert a ``presmed`` row attached to the given prescription."""
    session.execute(
        text(
            "INSERT INTO demo.presmed "
            "(fkpresmed, fkprescricao, fkmedicamento, fkunidademedida, "
            "fkfrequencia, dose, frequenciadia, via, origem, status) "
            "VALUES (:id, :prescription, :drug, 'mg', '1x', 100, 1, 'VO', "
            "'Medicamentos', '0')"
        ),
        {
            "id": id_prescription_drug,
            "prescription": id_prescription,
            "drug": id_drug,
        },
    )


def _delete_cohort():
    """Remove every row the cohort fixture creates."""
    admissions = tuple(_ADMISSIONS)
    session.execute(
        text(
            "DELETE FROM demo.presmed WHERE fkprescricao IN "
            "(SELECT fkprescricao FROM demo.prescricao WHERE nratendimento IN "
            ":admissions)"
        ),
        {"admissions": admissions},
    )
    session.execute(
        text("DELETE FROM demo.prescricao WHERE nratendimento IN :admissions"),
        {"admissions": admissions},
    )
    session.execute(
        text("DELETE FROM demo.pessoa WHERE nratendimento IN :admissions"),
        {"admissions": admissions},
    )
    session_commit()


@pytest.fixture
def cohort():
    """Build the three admissions the copy tests operate on.

    ``ADMISSION_STANDARD`` carries two open prescriptions with *different*
    expiry dates, so the non-CPOE branch — which keeps only the drugs of the
    latest expiry group — has something to discard.

    ``ADMISSION_CPOE`` carries two open prescriptions in a CPOE segment, where
    every drug is copied regardless of expiry.

    ``ADMISSION_WITHOUT_AGG`` has no aggregated prescription at all.
    """
    _delete_cohort()

    for admission in _ADMISSIONS:
        _insert_patient(admission)

    # --- non-CPOE admission
    _insert_prescription(
        id_prescription=PRESC_AGG_STANDARD,
        admission_number=ADMISSION_STANDARD,
        id_department=DEPARTMENT_STANDARD,
        date=AGG_DATE,
        expire=datetime(2026, 1, 11),
        agg=True,
    )
    _insert_prescription(
        id_prescription=PRESC_OLD_GROUP,
        admission_number=ADMISSION_STANDARD,
        id_department=DEPARTMENT_STANDARD,
        date=datetime(2026, 1, 8),
        expire=datetime(2026, 1, 10),
        agg=None,
    )
    _insert_prescription(
        id_prescription=PRESC_NEW_GROUP,
        admission_number=ADMISSION_STANDARD,
        id_department=DEPARTMENT_STANDARD,
        date=datetime(2026, 1, 9),
        expire=datetime(2026, 1, 12),
        agg=None,
    )
    _insert_prescription_drug(DRUG_OLD_GROUP, PRESC_OLD_GROUP, id_drug=3)
    _insert_prescription_drug(DRUG_NEW_GROUP, PRESC_NEW_GROUP, id_drug=4)

    # --- CPOE admission
    _insert_prescription(
        id_prescription=PRESC_AGG_CPOE,
        admission_number=ADMISSION_CPOE,
        id_department=DEPARTMENT_CPOE,
        date=AGG_DATE,
        expire=datetime(2026, 1, 11),
        agg=True,
    )
    _insert_prescription(
        id_prescription=PRESC_CPOE_A,
        admission_number=ADMISSION_CPOE,
        id_department=DEPARTMENT_CPOE,
        date=datetime(2026, 1, 8),
        expire=datetime(2026, 1, 10),
        agg=None,
    )
    _insert_prescription(
        id_prescription=PRESC_CPOE_B,
        admission_number=ADMISSION_CPOE,
        id_department=DEPARTMENT_CPOE,
        date=datetime(2026, 1, 9),
        expire=datetime(2026, 1, 12),
        agg=None,
    )
    _insert_prescription_drug(DRUG_CPOE_A, PRESC_CPOE_A, id_drug=3)
    _insert_prescription_drug(DRUG_CPOE_B, PRESC_CPOE_B, id_drug=4)

    # --- admission with no aggregated prescription
    _insert_prescription(
        id_prescription=991301,
        admission_number=ADMISSION_WITHOUT_AGG,
        id_department=DEPARTMENT_STANDARD,
        date=datetime(2026, 1, 9),
        expire=datetime(2026, 1, 12),
        agg=None,
    )

    session_commit()

    yield

    _delete_cohort()


@pytest.fixture
def fernet(monkeypatch):
    """Install a throwaway ENCRYPTION_KEY and return the matching Fernet."""
    key = Fernet.generate_key()
    monkeypatch.setattr(Config, "ENCRYPTION_KEY", key.decode("utf-8"))
    return Fernet(key)


@pytest.fixture
def lambda_client():
    """Patch the boto3 Lambda client and return the MagicMock standing in for it.

    ``utils.aws.get_client`` is memoised, so the module attribute is patched
    rather than the boto3 factory underneath it. The default response is a
    successful copy; tests override ``invoke.return_value`` when they need a
    different one.
    """
    client = MagicMock()
    client.invoke.return_value = _lambda_response({"status": "success"})

    with patch("services.navigation_service.aws.get_client", return_value=client):
        yield client


def _lambda_response(payload):
    """Wrap a dict the way boto3 returns a Lambda RequestResponse invocation."""
    return {"Payload": io.BytesIO(json.dumps(payload).encode("utf-8"))}


def _body(admission_number, name=PATIENT_NAME, phone=PATIENT_PHONE, notes=None):
    """Build a valid request body for the copy endpoint."""
    return {
        "admission_number": admission_number,
        "name": name,
        "phone": phone,
        "clinical_notes": {"admission": "zztest note"} if notes is None else notes,
    }


def _sent_payload(lambda_client):
    """Decode the JSON payload handed to the Lambda invocation."""
    assert lambda_client.invoke.call_count == 1
    return json.loads(lambda_client.invoke.call_args.kwargs["Payload"])


def _decrypt(fernet, value):
    """Reverse ``cryptutils.encrypt_data`` for an encrypted payload field."""
    return fernet.decrypt(base64.b64decode(value)).decode("utf-8")


# --- guards ----------------------------------------------------------------


def test_copy_requires_the_nav_permission(client, cohort):
    """An analyst has no NAV_COPY_PATIENT permission, so the copy is refused."""
    headers = make_headers(get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value]))

    response = client.post(URL, json=_body(ADMISSION_STANDARD), headers=headers)

    assert response.status_code == 401


def test_copy_rejects_an_incomplete_body(client, navigator_headers, cohort):
    """Every NavCopyPatientRequest field is required [400]."""
    response = client.post(
        URL,
        json={"admission_number": ADMISSION_STANDARD},
        headers=navigator_headers,
    )

    assert response.status_code == 400


def test_copy_rejects_an_admission_without_an_aggregated_prescription(
    client, navigator_headers, cohort, lambda_client
):
    """Without an aggregated prescription there is nothing to copy [400]."""
    response = client.post(
        URL, json=_body(ADMISSION_WITHOUT_AGG), headers=navigator_headers
    )

    assert response.status_code == 400
    assert response.get_json()["message"] == "Não há prescrição para este atendimento"
    lambda_client.invoke.assert_not_called()


# --- happy path ------------------------------------------------------------


def test_copy_returns_the_lambda_response(
    client, navigator_headers, cohort, fernet, lambda_client
):
    """The Lambda payload is returned to the caller untouched."""
    lambda_client.invoke.return_value = _lambda_response(
        {"status": "success", "admission_number": 4242}
    )

    response = client.post(
        URL, json=_body(ADMISSION_STANDARD), headers=navigator_headers
    )

    assert response.status_code == 200
    assert response.get_json()["data"] == {
        "status": "success",
        "admission_number": 4242,
    }


def test_copy_sends_the_admission_context_to_the_lambda(
    client, navigator_headers, cohort, fernet, lambda_client
):
    """The payload names the command, both schemas and the admission context."""
    client.post(URL, json=_body(ADMISSION_STANDARD), headers=navigator_headers)

    payload = _sent_payload(lambda_client)

    assert payload["command"] == "lambda_navigation.copy_patient_prescription"
    assert payload["from_schema"] == "demo"
    assert payload["to_schema"] == "demo"
    assert payload["from_admission_number"] == ADMISSION_STANDARD
    assert payload["id_department"] == DEPARTMENT_STANDARD
    assert payload["bed"] == BED
    assert payload["insurance"] == INSURANCE
    assert payload["encrypted"] is True


def test_copy_keeps_only_the_latest_expiry_group_outside_cpoe(
    client, navigator_headers, cohort, fernet, lambda_client
):
    """Outside CPOE only the drugs of the latest expiry date are copied."""
    client.post(URL, json=_body(ADMISSION_STANDARD), headers=navigator_headers)

    assert _sent_payload(lambda_client)["drug_list"] == [DRUG_NEW_GROUP]


def test_copy_keeps_every_drug_in_cpoe(
    client, navigator_headers, cohort, fernet, lambda_client
):
    """In a CPOE segment the expiry grouping is skipped and all drugs go."""
    client.post(URL, json=_body(ADMISSION_CPOE), headers=navigator_headers)

    assert sorted(_sent_payload(lambda_client)["drug_list"]) == [
        DRUG_CPOE_A,
        DRUG_CPOE_B,
    ]


# --- encryption ------------------------------------------------------------


def test_copy_encrypts_the_patient_identity(
    client, navigator_headers, cohort, fernet, lambda_client
):
    """Name and phone travel encrypted, never in clear text."""
    client.post(URL, json=_body(ADMISSION_STANDARD), headers=navigator_headers)

    payload = _sent_payload(lambda_client)

    assert payload["patient_name"] != PATIENT_NAME
    assert payload["patient_phone"] != PATIENT_PHONE
    assert _decrypt(fernet, payload["patient_name"]) == PATIENT_NAME
    assert _decrypt(fernet, payload["patient_phone"]) == PATIENT_PHONE


def test_copy_encrypts_every_clinical_note(
    client, navigator_headers, cohort, fernet, lambda_client
):
    """Each clinical note value is encrypted under its own key."""
    notes = {"admission": "zztest admission note", "evolution": "zztest evolution"}

    client.post(
        URL,
        json=_body(ADMISSION_STANDARD, notes=notes),
        headers=navigator_headers,
    )

    encrypted = _sent_payload(lambda_client)["clinical_notes"]

    assert set(encrypted.keys()) == set(notes.keys())
    for key, value in notes.items():
        assert encrypted[key] != value
        assert _decrypt(fernet, encrypted[key]) == value


def test_copy_truncates_a_long_clinical_note(
    client, navigator_headers, cohort, fernet, lambda_client
):
    """Notes are capped at 5000 characters and marked as truncated."""
    long_note = "palavra " * 1000  # 8000 characters

    client.post(
        URL,
        json=_body(ADMISSION_STANDARD, notes={"admission": long_note}),
        headers=navigator_headers,
    )

    stored = _decrypt(
        fernet, _sent_payload(lambda_client)["clinical_notes"]["admission"]
    )

    assert len(stored) <= 5000
    assert stored.endswith("... [truncado]")


def test_copy_nulls_out_non_string_clinical_notes(
    client, navigator_headers, cohort, fernet, lambda_client
):
    """Empty or non-string note values are sent as None instead of ciphertext."""
    client.post(
        URL,
        json=_body(
            ADMISSION_STANDARD,
            notes={"admission": "", "evolution": 42, "exam": None},
        ),
        headers=navigator_headers,
    )

    assert _sent_payload(lambda_client)["clinical_notes"] == {
        "admission": None,
        "evolution": None,
        "exam": None,
    }


def test_copy_sends_no_clinical_notes_when_the_dict_is_empty(
    client, navigator_headers, cohort, fernet, lambda_client
):
    """An empty clinical_notes dict stays empty in the payload."""
    client.post(
        URL,
        json=_body(ADMISSION_STANDARD, notes={}),
        headers=navigator_headers,
    )

    assert _sent_payload(lambda_client)["clinical_notes"] == {}


# --- lambda failure --------------------------------------------------------


def test_copy_reports_a_lambda_error_as_a_server_error(
    client, navigator_headers, cohort, fernet, lambda_client
):
    """An "error" key in the Lambda response surfaces as a 500 to the caller."""
    lambda_client.invoke.return_value = _lambda_response(
        {"error": True, "message": "zztest lambda failure"}
    )

    response = client.post(
        URL, json=_body(ADMISSION_STANDARD), headers=navigator_headers
    )

    assert response.status_code == 500
    assert "Ocorreu um erro ao copiar" in response.get_json()["message"]
