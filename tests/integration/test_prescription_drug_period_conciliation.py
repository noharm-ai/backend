"""Tests: future drug period of a conciliation item (services.prescription_drug_service._getDrugFuture).

A conciliation item has no drug (``fkmedicamento = 0``): the drug name the patient
reported lives in ``presmed.intervalo``. To answer ``GET /prescriptions/drug/<id>/period?future``
for it, the service asks the AI lambda (``admin_ai_service.get_substance_by_drug_name``)
for the substance of that name and lists the admission's prescriptions of any drug of
that substance. The lambda is stubbed here; without a substance the item falls back to
the plain drug query, which matches nothing.
"""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import text

from tests.conftest import session, session_commit
from tests.utils.utils_test_prescription import (
    create_prescription,
    create_prescription_drug,
    test_counters,
)
from tests.utils.utils_test_unit_conversion import create_test_drug

_SUBSTANCE = 91601000
_OTHER_SUBSTANCE = 91602000
_DRUG_A = 91601
_DRUG_B = 91602
_DRUG_OTHER_SUBSTANCE = 91603
_CONCILIATION_NAME = "ZZTEST LOSARTANA 50MG"

_AI_PATH = "services.admin.admin_ai_service.get_substance_by_drug_name"


def _delete_test_drugs():
    """Remove the drugs this module creates."""
    session.execute(
        text("DELETE FROM demo.medicamento WHERE fkmedicamento IN (:a, :b, :c)"),
        {"a": _DRUG_A, "b": _DRUG_B, "c": _DRUG_OTHER_SUBSTANCE},
    )
    session_commit()


@pytest.fixture(autouse=True)
def substance_drugs():
    """Two drugs of the inferred substance and one of another substance."""
    _delete_test_drugs()
    create_test_drug(id=_DRUG_A, name="ZZTEST Losartana A", sctid=_SUBSTANCE)
    create_test_drug(id=_DRUG_B, name="ZZTEST Losartana B", sctid=_SUBSTANCE)
    create_test_drug(
        id=_DRUG_OTHER_SUBSTANCE, name="ZZTEST Outra", sctid=_OTHER_SUBSTANCE
    )
    yield
    _delete_test_drugs()


def _next_ids():
    """Reserve a unique prescription id and admission number for a test."""
    id_prescription = test_counters["id_prescription"]
    admission_number = test_counters["admission_number"]
    test_counters["id_prescription"] += 1
    test_counters["admission_number"] += 1
    return id_prescription, admission_number


def _conciliation(admission: int, id_prescription: int) -> int:
    """Create a conciliation prescription with one item without drug; returns the presmed id."""
    create_prescription(
        id=id_prescription,
        admissionNumber=admission,
        idPatient=1,
        date=datetime.now() - timedelta(days=1),
        concilia="s",
    )
    id_pd = int(f"{id_prescription}001")
    create_prescription_drug(
        id=id_pd,
        idPrescription=id_prescription,
        idDrug=0,
        interval=_CONCILIATION_NAME,
    )
    return id_pd


def _later_prescription(
    admission: int, id_prescription: int, drugs: list, offset=timedelta(0), **kwargs
):
    """Create a later prescription of the admission holding the given drugs."""
    create_prescription(
        id=id_prescription,
        admissionNumber=admission,
        idPatient=1,
        date=datetime.now() + offset,
        **kwargs,
    )
    for index, id_drug in enumerate(drugs, start=1):
        create_prescription_drug(
            id=int(f"{id_prescription}00{index}"),
            idPrescription=id_prescription,
            idDrug=id_drug,
            dose=50.0,
        )


def _get_future(client, headers, id_pd: int):
    """Call the future period endpoint for a presmed."""
    return client.get(f"/prescriptions/drug/{id_pd}/period?future=1", headers=headers)


def test_lists_prescriptions_of_drugs_with_the_inferred_substance(
    client, analyst_headers
):
    """GET /prescriptions/drug/<id>/period?future - a conciliation item lists every drug of its substance"""
    id_conciliation, admission = _next_ids()
    id_first, _ = _next_ids()
    id_second, _ = _next_ids()

    id_pd = _conciliation(admission, id_conciliation)
    _later_prescription(admission, id_first, [_DRUG_A])
    _later_prescription(admission, id_second, [_DRUG_B], offset=timedelta(hours=1))

    with patch(_AI_PATH, return_value={_CONCILIATION_NAME: _SUBSTANCE}) as ai:
        response = _get_future(client, analyst_headers, id_pd)

    assert response.status_code == 200
    ai.assert_called_once_with(drug_names=[_CONCILIATION_NAME])

    today = datetime.now().strftime("%d/%m")
    later = (datetime.now() + timedelta(hours=1)).strftime("%d/%m")
    # ordered by prescription date
    assert response.get_json()["data"] == [
        f"{id_first} = {today} (1x 50 mg) via VO; ",
        f"{id_second} = {later} (1x 50 mg) via VO; ",
    ]


def test_ignores_drugs_of_another_substance(client, analyst_headers):
    """GET /prescriptions/drug/<id>/period?future - a drug of another substance is not listed"""
    id_conciliation, admission = _next_ids()
    id_later, _ = _next_ids()

    id_pd = _conciliation(admission, id_conciliation)
    _later_prescription(admission, id_later, [_DRUG_OTHER_SUBSTANCE, _DRUG_A])

    with patch(_AI_PATH, return_value={_CONCILIATION_NAME: _SUBSTANCE}):
        response = _get_future(client, analyst_headers, id_pd)

    assert response.status_code == 200

    period = response.get_json()["data"]
    assert len(period) == 1
    assert period[0].startswith(f"{id_later} = ")


def test_ignores_suspended_items_and_other_conciliations(client, analyst_headers):
    """GET /prescriptions/drug/<id>/period?future - suspended items and conciliations are left out"""
    id_conciliation, admission = _next_ids()
    id_other_conciliation, _ = _next_ids()
    id_suspended, _ = _next_ids()

    id_pd = _conciliation(admission, id_conciliation)
    _later_prescription(admission, id_other_conciliation, [_DRUG_A], concilia="s")
    _later_prescription(admission, id_suspended, [_DRUG_B])
    session.execute(
        text("UPDATE demo.presmed SET dtsuspensao = now() WHERE fkprescricao = :id"),
        {"id": id_suspended},
    )
    session_commit()

    with patch(_AI_PATH, return_value={_CONCILIATION_NAME: _SUBSTANCE}):
        response = _get_future(client, analyst_headers, id_pd)

    assert response.status_code == 200
    assert response.get_json()["data"] == [
        "Não há prescrição posterior para esse Medicamento"
    ]


def test_ignores_prescriptions_of_another_admission(client, analyst_headers):
    """GET /prescriptions/drug/<id>/period?future - only the conciliation's admission counts"""
    id_conciliation, admission = _next_ids()
    id_other, other_admission = _next_ids()

    id_pd = _conciliation(admission, id_conciliation)
    _later_prescription(other_admission, id_other, [_DRUG_A])

    with patch(_AI_PATH, return_value={_CONCILIATION_NAME: _SUBSTANCE}):
        response = _get_future(client, analyst_headers, id_pd)

    assert response.status_code == 200
    assert response.get_json()["data"] == [
        "Não há prescrição posterior para esse Paciente"
    ]


def test_without_an_inferred_substance_nothing_is_listed(client, analyst_headers):
    """GET /prescriptions/drug/<id>/period?future - no substance falls back to the drug query"""
    id_conciliation, admission = _next_ids()
    id_later, _ = _next_ids()

    id_pd = _conciliation(admission, id_conciliation)
    _later_prescription(admission, id_later, [_DRUG_A])

    # the lambda does not know the name
    with patch(_AI_PATH, return_value={}):
        response = _get_future(client, analyst_headers, id_pd)

    assert response.status_code == 200
    assert response.get_json()["data"] == [
        "Não há prescrição posterior para esse Medicamento"
    ]


def test_a_regular_item_does_not_ask_for_the_substance(client, analyst_headers):
    """GET /prescriptions/drug/<id>/period?future - an item with a drug never calls the AI lambda"""
    id_current, admission = _next_ids()
    id_later, _ = _next_ids()

    create_prescription(
        id=id_current,
        admissionNumber=admission,
        idPatient=1,
        date=datetime.now() - timedelta(days=1),
    )
    id_pd = int(f"{id_current}001")
    create_prescription_drug(id=id_pd, idPrescription=id_current, idDrug=_DRUG_A)
    _later_prescription(admission, id_later, [_DRUG_B])

    with patch(_AI_PATH) as ai:
        response = _get_future(client, analyst_headers, id_pd)

    assert response.status_code == 200
    ai.assert_not_called()
    # the plain query matches the same drug only, not its substance
    assert response.get_json()["data"] == [
        "Não há prescrição posterior para esse Medicamento"
    ]
