import json

from tests.conftest import get_access, make_headers

from security.role import Role


def test_get_prescriptions_response_structure(client):
    """GET /prescriptions deve retornar lista com campos obrigatórios"""
    access_token = get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value])

    response = client.get(
        "/prescriptions?startDate=2020-12-31", headers=make_headers(access_token)
    )
    body = json.loads(response.data)

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


def test_get_prescriptions_filter_by_segment_list(client):
    """GET /prescriptions?idSegment[]=1 deve retornar apenas prescrições do segmento 1"""
    access_token = get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value])

    response = client.get(
        "/prescriptions?idSegment[]=1&startDate=2020-12-31",
        headers=make_headers(access_token),
    )
    data = json.loads(response.data)["data"]

    assert response.status_code == 200
    assert len(data) > 0
    for item in data:
        assert item["idSegment"] == 1


def test_get_prescriptions_filter_pending(client):
    """GET /prescriptions?pending=true deve retornar apenas prescrições pendentes"""
    access_token = get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value])

    response = client.get(
        "/prescriptions?pending=true&startDate=2020-12-31",
        headers=make_headers(access_token),
    )
    data = json.loads(response.data)["data"]

    assert response.status_code == 200
    for item in data:
        assert item["status"] == "0"


def test_get_prescriptions_filter_agg(client):
    """GET /prescriptions?agg=true deve retornar apenas prescrições agregadas"""
    access_token = get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value])

    response = client.get(
        "/prescriptions?agg=true&startDate=2020-12-31",
        headers=make_headers(access_token),
    )
    data = json.loads(response.data)["data"]

    assert response.status_code == 200
    for item in data:
        assert item["agg"] is True
        assert item.get("concilia") is None


def test_get_prescriptions_filter_concilia(client):
    """GET /prescriptions?concilia=true deve retornar apenas prescrições com conciliação"""
    access_token = get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value])

    response = client.get(
        "/prescriptions?concilia=true&startDate=2020-12-31",
        headers=make_headers(access_token),
    )
    data = json.loads(response.data)["data"]

    assert response.status_code == 200
    for item in data:
        assert item.get("concilia") is not None
