from datetime import datetime

from tests.utils.utils_test_prescription import (
    create_prescription,
    create_prescription_drug,
    test_counters,
)


# Seed prescriptions in the test database are dated 2020-12-31
SEED_DATE = datetime(2020, 12, 31, 10, 0)


def test_get_prescriptions_response_structure(client, analyst_headers):
    """GET /prescriptions deve retornar lista com campos obrigatórios"""
    response = client.get(
        "/prescriptions?startDate=2020-12-31", headers=analyst_headers
    )
    body = response.get_json()

    assert response.status_code == 200
    assert "data" in body
    assert isinstance(body["data"], list)
    assert len(body["data"]) > 0

    item = body["data"][0]
    assert "idPrescription" in item
    assert "status" in item
    assert "idSegment" in item
    assert "globalScore" in item
    assert "class" in item


def test_get_prescriptions_filter_by_segment_list(client, analyst_headers):
    """GET /prescriptions?idSegment[]=1 deve retornar apenas prescrições do segmento 1"""
    response = client.get(
        "/prescriptions?idSegment[]=1&startDate=2020-12-31",
        headers=analyst_headers,
    )
    data = response.get_json()["data"]

    assert response.status_code == 200
    assert len(data) > 0
    for item in data:
        assert item["idSegment"] == 1


def test_get_prescriptions_filter_pending(client, analyst_headers):
    """GET /prescriptions?pending=true deve retornar apenas prescrições pendentes"""
    response = client.get(
        "/prescriptions?pending=true&startDate=2020-12-31",
        headers=analyst_headers,
    )
    data = response.get_json()["data"]

    assert response.status_code == 200
    for item in data:
        assert item["status"] == "0"


def test_get_prescriptions_filter_agg(client, analyst_headers):
    """GET /prescriptions?agg=true deve retornar apenas prescrições agregadas"""
    response = client.get(
        "/prescriptions?agg=true&startDate=2020-12-31",
        headers=analyst_headers,
    )
    data = response.get_json()["data"]

    assert response.status_code == 200
    for item in data:
        assert item["agg"] is True
        assert item.get("concilia") is None


def test_get_prescriptions_filter_concilia(client, analyst_headers):
    """GET /prescriptions?concilia=true deve retornar apenas prescrições com conciliação"""
    response = client.get(
        "/prescriptions?concilia=true&startDate=2020-12-31",
        headers=analyst_headers,
    )
    data = response.get_json()["data"]

    assert response.status_code == 200
    for item in data:
        assert item.get("concilia") is not None


def test_get_prescriptions_includes_agg_false(client, analyst_headers):
    """Prescrições com agg=False devem ser tratadas como não agregadas (agg NULL ou False)"""
    id_pres = test_counters["id_prescription"]
    adm = test_counters["admission_number"]

    create_prescription(
        id=id_pres,
        admissionNumber=adm,
        idPatient=1,
        agg=False,
        date=SEED_DATE,
    )
    create_prescription_drug(
        id=int(f"{id_pres}001"),
        idPrescription=id_pres,
        idDrug=3,
    )
    test_counters["id_prescription"] += 1
    test_counters["admission_number"] += 1

    response = client.get(
        "/prescriptions?startDate=2020-12-31", headers=analyst_headers
    )
    data = response.get_json()["data"]

    assert response.status_code == 200
    assert id_pres in [int(i["idPrescription"]) for i in data]


def test_get_prescriptions_filter_agg_excludes_agg_false(client, analyst_headers):
    """GET /prescriptions?agg=true não deve retornar prescrições com agg=False"""
    id_pres = test_counters["id_prescription"]
    adm = test_counters["admission_number"]

    create_prescription(
        id=id_pres,
        admissionNumber=adm,
        idPatient=1,
        agg=False,
        date=SEED_DATE,
    )
    test_counters["id_prescription"] += 1
    test_counters["admission_number"] += 1

    response = client.get(
        "/prescriptions?agg=true&startDate=2020-12-31",
        headers=analyst_headers,
    )
    data = response.get_json()["data"]

    assert response.status_code == 200
    assert id_pres not in [int(i["idPrescription"]) for i in data]
