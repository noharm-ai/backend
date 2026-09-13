"""Tests: Drug period endpoint (services.prescription_drug_service.get_drug_period).

``GET /prescriptions/drug/<id>/period`` answers "when else was this drug prescribed
for this admission?". Without the ``future`` flag it lists the previous prescriptions
of the last 30 days; with it, the prescriptions that come after the current one.
Both lists skip suspended items, and the frequency codes the database stores as
numbers (33, 44, 55, 66, 99) are rendered with their clinical labels.
"""

from datetime import datetime, timedelta

from sqlalchemy import text

from security.role import Role
from tests.conftest import get_access, make_headers, session, session_commit
from tests.utils.utils_test_prescription import (
    create_prescription,
    create_prescription_drug,
    test_counters,
)

ADULT_SEGMENT = 1
CPOE_SEGMENT = 2


def _next_ids():
    """Reserve a unique prescription id and admission number for a test."""
    id_prescription = test_counters["id_prescription"]
    admission_number = test_counters["admission_number"]
    test_counters["id_prescription"] += 1
    test_counters["admission_number"] += 1
    return id_prescription, admission_number


def _admission_with_two_prescriptions(
    id_drug=3,
    previous_offset=timedelta(days=2),
    previous_dose=100.0,
    previous_frequency=1.0,
    previous_suspended=None,
    id_segment=ADULT_SEGMENT,
    id_department=1,
):
    """Create one admission holding an older and a newer prescription of the same drug.

    Returns the presmed ids of the older and the newer prescription, in that order.
    """
    id_previous, admission = _next_ids()
    id_current, _ = _next_ids()

    create_prescription(
        id=id_previous,
        admissionNumber=admission,
        idPatient=1,
        idSegment=id_segment,
        idDepartment=id_department,
        date=datetime.now() - previous_offset,
        expire=datetime.now() - previous_offset + timedelta(days=1),
    )
    create_prescription(
        id=id_current,
        admissionNumber=admission,
        idPatient=1,
        idSegment=id_segment,
        idDepartment=id_department,
        date=datetime.now(),
    )

    id_pd_previous = int(f"{id_previous}001")
    id_pd_current = int(f"{id_current}001")

    create_prescription_drug(
        id=id_pd_previous,
        idPrescription=id_previous,
        idDrug=id_drug,
        idSegment=id_segment,
        dose=previous_dose,
        frequency=previous_frequency,
        suspendedDate=previous_suspended,
    )
    create_prescription_drug(
        id=id_pd_current,
        idPrescription=id_current,
        idDrug=id_drug,
        idSegment=id_segment,
    )

    return id_pd_previous, id_pd_current


def test_period_lists_the_previous_prescription(client, analyst_headers):
    """GET /prescriptions/drug/<id>/period - lists the earlier prescription of the same drug"""
    _, id_pd_current = _admission_with_two_prescriptions()

    response = client.get(
        f"/prescriptions/drug/{id_pd_current}/period", headers=analyst_headers
    )

    assert response.status_code == 200

    expected_date = (datetime.now() - timedelta(days=2)).strftime("%d/%m")
    assert response.get_json()["data"] == [f"{expected_date} (1x 100,00 mg)"]


def test_period_formats_the_dose_with_brazilian_separators(client, analyst_headers):
    """GET /prescriptions/drug/<id>/period - formats the dose as 1.234,56"""
    _, id_pd_current = _admission_with_two_prescriptions(previous_dose=1234.56)

    response = client.get(
        f"/prescriptions/drug/{id_pd_current}/period", headers=analyst_headers
    )

    assert response.status_code == 200
    assert "(1x 1.234,56 mg)" in response.get_json()["data"][0]


def test_period_translates_the_frequency_codes(client, analyst_headers):
    """GET /prescriptions/drug/<id>/period - renders frequency 33 as the "if needed" label"""
    _, id_pd_current = _admission_with_two_prescriptions(previous_frequency=33.0)

    response = client.get(
        f"/prescriptions/drug/{id_pd_current}/period", headers=analyst_headers
    )

    assert response.status_code == 200
    assert "(SNx 100,00 mg)" in response.get_json()["data"][0]


def test_period_skips_suspended_prescriptions(client, analyst_headers):
    """GET /prescriptions/drug/<id>/period - a suspended earlier item is left out"""
    _, id_pd_current = _admission_with_two_prescriptions(
        previous_suspended=datetime.now() - timedelta(days=1)
    )

    response = client.get(
        f"/prescriptions/drug/{id_pd_current}/period", headers=analyst_headers
    )

    assert response.status_code == 200
    assert response.get_json()["data"] == []


def test_period_ignores_prescriptions_older_than_30_days(client, analyst_headers):
    """GET /prescriptions/drug/<id>/period - the history window stops at 30 days"""
    _, id_pd_current = _admission_with_two_prescriptions(
        previous_offset=timedelta(days=45)
    )

    response = client.get(
        f"/prescriptions/drug/{id_pd_current}/period", headers=analyst_headers
    )

    assert response.status_code == 200
    assert response.get_json()["data"] == []


def test_period_ignores_other_drugs_of_the_same_admission(client, analyst_headers):
    """GET /prescriptions/drug/<id>/period - only the same drug counts as history"""
    id_previous, admission = _next_ids()
    id_current, _ = _next_ids()

    create_prescription(
        id=id_previous,
        admissionNumber=admission,
        idPatient=1,
        date=datetime.now() - timedelta(days=1),
    )
    create_prescription(
        id=id_current, admissionNumber=admission, idPatient=1, date=datetime.now()
    )
    create_prescription_drug(
        id=int(f"{id_previous}001"), idPrescription=id_previous, idDrug=4
    )
    id_pd_current = int(f"{id_current}001")
    create_prescription_drug(id=id_pd_current, idPrescription=id_current, idDrug=3)

    response = client.get(
        f"/prescriptions/drug/{id_pd_current}/period", headers=analyst_headers
    )

    assert response.status_code == 200
    assert response.get_json()["data"] == []


def test_period_of_an_unknown_drug_returns_an_empty_list(client, analyst_headers):
    """GET /prescriptions/drug/<id>/period - an unknown presmed id yields no period"""
    response = client.get(
        "/prescriptions/drug/100999999/period", headers=analyst_headers
    )

    assert response.status_code == 200
    assert response.get_json()["data"] == []


def test_period_of_an_intervention_without_drug(client, analyst_headers):
    """GET /prescriptions/drug/0/period - explains that the intervention has no drug"""
    response = client.get("/prescriptions/drug/0/period", headers=analyst_headers)

    assert response.status_code == 200
    assert response.get_json()["data"] == [
        "Intervenção no paciente não possui medicamento associado."
    ]


def test_period_requires_read_permission(client, user_manager_headers):
    """GET /prescriptions/drug/<id>/period - returns 401 without READ_PRESCRIPTION"""
    _, id_pd_current = _admission_with_two_prescriptions()

    response = client.get(
        f"/prescriptions/drug/{id_pd_current}/period", headers=user_manager_headers
    )

    assert response.status_code == 401


def test_period_is_available_to_a_viewer(client, viewer_headers):
    """GET /prescriptions/drug/<id>/period - a read-only viewer may consult the period"""
    _, id_pd_current = _admission_with_two_prescriptions()

    response = client.get(
        f"/prescriptions/drug/{id_pd_current}/period", headers=viewer_headers
    )

    assert response.status_code == 200


def test_future_period_lists_the_next_prescription(client, analyst_headers):
    """GET /prescriptions/drug/<id>/period?future - lists the later prescription of the drug"""
    id_pd_previous, _ = _admission_with_two_prescriptions()

    response = client.get(
        f"/prescriptions/drug/{id_pd_previous}/period?future=1", headers=analyst_headers
    )

    assert response.status_code == 200

    period = response.get_json()["data"]
    assert len(period) == 1
    assert period[0].endswith("(1x 100 mg) via VO; ")
    assert datetime.now().strftime("%d/%m") in period[0]


def test_future_period_skips_suspended_prescriptions(client, analyst_headers):
    """GET /prescriptions/drug/<id>/period?future - a suspended later item is left out"""
    id_pd_previous, id_pd_current = _admission_with_two_prescriptions()

    session.execute(
        text("UPDATE demo.presmed SET dtsuspensao = now() WHERE fkpresmed = :id"),
        {"id": id_pd_current},
    )
    session_commit()

    response = client.get(
        f"/prescriptions/drug/{id_pd_previous}/period?future=1", headers=analyst_headers
    )

    assert response.status_code == 200
    assert response.get_json()["data"] == [
        "Não há prescrição posterior para esse Medicamento"
    ]


def test_future_period_without_a_later_prescription_for_the_drug(
    client, analyst_headers
):
    """GET /prescriptions/drug/<id>/period?future - reports that the drug was not prescribed again"""
    id_previous, admission = _next_ids()
    id_current, _ = _next_ids()

    create_prescription(
        id=id_previous,
        admissionNumber=admission,
        idPatient=1,
        date=datetime.now() - timedelta(days=1),
    )
    create_prescription(
        id=id_current, admissionNumber=admission, idPatient=1, date=datetime.now()
    )
    id_pd_previous = int(f"{id_previous}001")
    create_prescription_drug(id=id_pd_previous, idPrescription=id_previous, idDrug=3)
    create_prescription_drug(
        id=int(f"{id_current}001"), idPrescription=id_current, idDrug=4
    )

    response = client.get(
        f"/prescriptions/drug/{id_pd_previous}/period?future=1", headers=analyst_headers
    )

    assert response.status_code == 200
    assert response.get_json()["data"] == [
        "Não há prescrição posterior para esse Medicamento"
    ]


def test_future_period_without_any_later_prescription(client, analyst_headers):
    """GET /prescriptions/drug/<id>/period?future - reports that the patient has no later prescription"""
    id_prescription, admission = _next_ids()

    create_prescription(
        id=id_prescription,
        admissionNumber=admission,
        idPatient=1,
        date=datetime.now(),
    )
    id_pd = int(f"{id_prescription}001")
    create_prescription_drug(id=id_pd, idPrescription=id_prescription, idDrug=3)

    response = client.get(
        f"/prescriptions/drug/{id_pd}/period?future=1", headers=analyst_headers
    )

    assert response.status_code == 200
    assert response.get_json()["data"] == [
        "Não há prescrição posterior para esse Paciente"
    ]


def test_cpoe_period_reports_the_administration_window(client):
    """GET /prescriptions/drug/<id>/period - a CPOE segment reports a start/end window"""
    headers = make_headers(get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value]))
    id_pd_previous, id_pd_current = _admission_with_two_prescriptions(
        id_segment=CPOE_SEGMENT, id_department=3
    )

    response = client.get(
        f"/prescriptions/drug/{id_pd_current}/period", headers=headers
    )

    assert response.status_code == 200

    # each row spans from the prescription date to the date it expires
    period = response.get_json()["data"]
    previous_start = (datetime.now() - timedelta(days=2)).strftime("%d/%m")
    previous_end = (datetime.now() - timedelta(days=1)).strftime("%d/%m")
    today = datetime.now().strftime("%d/%m")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%d/%m")

    assert sorted(period) == sorted(
        [
            f"{previous_start} - {previous_end} (1x 100,00 mg)",
            f"{today} - {tomorrow} (1x 100,00 mg)",
        ]
    )
    assert id_pd_previous  # both items belong to the same admission window


def test_cpoe_period_flags_suspended_items(client):
    """GET /prescriptions/drug/<id>/period - a suspended CPOE item is marked as suspended"""
    headers = make_headers(get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value]))
    suspension = datetime.now() - timedelta(days=1)
    _, id_pd_current = _admission_with_two_prescriptions(
        id_segment=CPOE_SEGMENT,
        id_department=3,
        previous_offset=timedelta(days=5),
        previous_suspended=suspension,
    )

    response = client.get(
        f"/prescriptions/drug/{id_pd_current}/period", headers=headers
    )

    assert response.status_code == 200

    # the suspension date closes the window, taking precedence over the expire date
    period = response.get_json()["data"]
    start = (datetime.now() - timedelta(days=5)).strftime("%d/%m")
    assert (
        f"{start} - {suspension.strftime('%d/%m')} (1x 100,00 mg) - suspenso"
    ) in period
