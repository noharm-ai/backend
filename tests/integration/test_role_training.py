"""Tests for the TRAINING role: read-only app access plus MULTI_SCHEMA."""

from models.appendix import SchemaConfig
from models.enums import FeatureEnum
from security.permission import Permission
from security.role import Role
from tests.conftest import session

PRESCRIPTION = "20"
PRESCRIPTIONDRUG = "20"


def test_training_role_permissions():
    """TRAINING grants only read permissions plus MULTI_SCHEMA"""
    permissions = Role.TRAINING.permissions

    assert Permission.MULTI_SCHEMA in permissions
    assert set(permissions) == {
        Permission.READ_PRESCRIPTION,
        Permission.READ_REPORTS,
        Permission.READ_BASIC_FEATURES,
        Permission.READ_SUPPORT,
        Permission.READ_USERS,
        Permission.MULTI_SCHEMA,
        Permission.READ_CONFIG_EXAMS,
        Permission.READ_TAGS,
        Permission.TRAINING_RECORDING,
    }


def test_training_role_bypasses_oauth_gate_without_maintainer():
    """TRAINING bypasses the OAUTH feature gate without gaining MAINTAINER"""
    permissions = Role.TRAINING.permissions

    assert Permission.TRAINING_RECORDING in permissions
    assert Permission.MAINTAINER not in permissions


def test_training_role_has_no_write_permissions():
    """TRAINING must not hold any write/admin permission"""
    for permission in Role.TRAINING.permissions:
        assert not permission.value.startswith("WRITE_")
        assert not permission.value.startswith("ADMIN_")


def test_training_role_is_special():
    """TRAINING is not assignable through the regular user admin flow"""
    assert Role.TRAINING.value in Role.get_special_roles()


def test_training_can_list_prescriptions(client, training_headers):
    """GET /prescriptions — TRAINING reads the prescription list"""
    response = client.get("/prescriptions", headers=training_headers)

    assert response.status_code == 200


def test_training_can_view_prescription(client, training_headers):
    """GET /prescriptions/id — TRAINING reads a single prescription"""
    response = client.get("/prescriptions/" + PRESCRIPTION, headers=training_headers)

    assert response.status_code == 200
    assert response.get_json()["data"]["idPrescription"] == PRESCRIPTION


def test_training_cannot_update_prescription(client, training_headers):
    """PUT /prescriptions/id — TRAINING cannot write a prescription"""
    response = client.put(
        "/prescriptions/" + PRESCRIPTION,
        json={"notes": "note test", "concilia": "s"},
        headers=training_headers,
    )

    assert response.status_code == 401


def test_training_cannot_update_prescription_drug(client, training_headers):
    """PUT /prescriptions/drug/id — TRAINING cannot write a prescription drug"""
    response = client.put(
        f"/prescriptions/drug/{PRESCRIPTIONDRUG}",
        json={"notes": "some notes", "admissionNumber": 5},
        headers=training_headers,
    )

    assert response.status_code == 401


def test_training_can_read_switch_schema_data(client, training_headers):
    """GET /switch-schema — TRAINING lists every schema without maintainer privileges"""
    response = client.get("/switch-schema", headers=training_headers)

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["maintainer"] is False

    configured = [s.schemaName for s in session.query(SchemaConfig).all()]
    assert [s["name"] for s in data["schemas"]] == sorted(configured)


def test_training_can_switch_to_any_configured_schema(client, training_headers):
    """POST /switch-schema — TRAINING switches into a schema it was not listed for"""
    response = client.post(
        "/switch-schema", json={"schema": "teste"}, headers=training_headers
    )

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["schema"] == "teste"
    assert FeatureEnum.HIDE_NAMES.value in data["userFeatures"]


def test_training_cannot_switch_to_unknown_schema(client, training_headers):
    """POST /switch-schema — an unconfigured schema is rejected, not crashed on"""
    response = client.post(
        "/switch-schema", json={"schema": "other"}, headers=training_headers
    )

    assert response.status_code == 401


def test_admin_can_switch_to_training_role(client, admin_headers):
    """POST /switch-schema — ADMIN assumes the TRAINING role via runAsRole"""
    response = client.post(
        "/switch-schema",
        json={"schema": "teste", "runAsRole": Role.TRAINING.value},
        headers=admin_headers,
    )

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["roles"] == [Role.TRAINING.value]
    assert FeatureEnum.HIDE_NAMES.value in data["userFeatures"]
    assert FeatureEnum.DISABLE_GETNAME.value in data["userFeatures"]


def test_curator_can_switch_to_training_role(client, curator_headers):
    """POST /switch-schema — CURATOR assumes the TRAINING role via runAsRole"""
    response = client.post(
        "/switch-schema",
        json={"schema": "teste", "runAsRole": Role.TRAINING.value},
        headers=curator_headers,
    )

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["roles"] == [Role.TRAINING.value]


def test_regular_user_cannot_switch_to_training_role(client, training_headers):
    """POST /switch-schema — runAsRole is rejected without ADMIN/CURATOR"""
    response = client.post(
        "/switch-schema",
        json={"schema": "teste", "runAsRole": Role.TRAINING.value},
        headers=training_headers,
    )

    assert response.status_code == 401


def test_switch_to_other_role_is_rejected(client, admin_headers):
    """POST /switch-schema — runAsRole only accepts TRAINING"""
    response = client.post(
        "/switch-schema",
        json={"schema": "teste", "runAsRole": Role.ADMIN.value},
        headers=admin_headers,
    )

    assert response.status_code == 400


def test_training_cannot_check_prescription(client, training_headers):
    """POST /prescriptions/status — TRAINING cannot check a prescription"""
    response = client.post(
        "/prescriptions/status",
        json={"status": "s", "idPrescription": PRESCRIPTION},
        headers=training_headers,
    )

    assert response.status_code == 401
