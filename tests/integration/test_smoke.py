"""Smoke tests: cross-domain endpoint sanity checks"""


def test_health_check(client):
    """Teste get /version - Valida status_code 200."""
    response = client.get("/version")

    assert response.status_code == 200


def test_get_segments(client, analyst_headers):
    """Teste get /segments - Valida o status_code 200."""
    response = client.get("/segments", headers=analyst_headers)

    assert response.status_code == 200


def test_get_departments(client, analyst_headers):
    """Teste get /segments/departments - Valida o status_code 200."""
    response = client.get("/segments/departments", headers=analyst_headers)

    assert response.status_code == 200


def test_get_exam_types(client, config_manager_headers):
    """Teste get /admin/exam/types - Valida o status_code 200."""
    response = client.get("/admin/exam/types", headers=config_manager_headers)

    assert response.status_code == 200
