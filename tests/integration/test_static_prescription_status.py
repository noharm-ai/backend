"""Tests: static prescription check (POST /static/prescriptions/status)

The endpoint an external system calls to check a prescription on behalf of one
of its own users. The caller authenticates as a service integrator (RUN_AS) and
identifies the real author by their external id; the check is then recorded as
if that user had performed it.
"""

from datetime import datetime

import pytest
from sqlalchemy import func

from models.enums import PrescriptionAuditTypeEnum
from models.main import User, UserAuthorization
from models.prescription import Prescription, PrescriptionAudit
from security.role import Role
from tests.conftest import get_access, make_headers, session, session_commit
from tests.utils.utils_test_prescription import create_basic_prescription

STATIC_CHECK_URL = "/static/prescriptions/status"

# emails follow the pattern wiped by tests/conftest.py::_cleanup
ANALYST_EMAIL = "test-static-analyst@example.com"
VIEWER_EMAIL = "test-static-viewer@example.com"
INACTIVE_EMAIL = "test-static-inactive@example.com"
FOREIGN_EMAIL = "test-static-foreign@example.com"
UNAUTHORIZED_EMAIL = "test-static-nosegment@example.com"

ANALYST_EXTERNAL = "ZZTEST-EXT-ANALYST"
VIEWER_EXTERNAL = "ZZTEST-EXT-VIEWER"
INACTIVE_EXTERNAL = "ZZTEST-EXT-INACTIVE"
FOREIGN_EXTERNAL = "ZZTEST-EXT-FOREIGN"
UNAUTHORIZED_EXTERNAL = "ZZTEST-EXT-NOSEGMENT"

# the demo schema runs with AUTHORIZATION_SEGMENT on, so an origin user only
# reaches the check once it is authorized on the prescription's segment
SEED_SEGMENT = 1

TEST_EMAILS = (
    ANALYST_EMAIL,
    VIEWER_EMAIL,
    INACTIVE_EMAIL,
    FOREIGN_EMAIL,
    UNAUTHORIZED_EMAIL,
)


def _payload(id_prescription, status="s", id_origin_user=ANALYST_EXTERNAL):
    return {
        "idPrescription": id_prescription,
        "status": status,
        "idOriginUser": id_origin_user,
    }


def _create_origin_user(
    email, external, roles, active=True, schema="demo", id_segment=SEED_SEGMENT
):
    """Create (or recreate) a user the static check can run as"""
    _delete_origin_user(email)

    user = User()
    user.email = email
    user.name = "Fulano Integracao"
    user.schema = schema
    user.external = external
    user.active = active
    user.config = {"roles": roles, "features": []}
    user.password = func.crypt("zztest-static", func.gen_salt("bf", 8))

    session.add(user)
    session_commit()
    session.refresh(user)

    if id_segment is not None:
        authorization = UserAuthorization()
        authorization.idUser = user.id
        authorization.idSegment = id_segment
        authorization.createdAt = datetime.today()
        authorization.createdBy = user.id

        session.add(authorization)
        session_commit()

    return user


def _delete_origin_user(email):
    """Drop the user and the segment authorizations left behind by a prior run"""
    ids = [row.id for row in session.query(User.id).filter(User.email == email).all()]
    if ids:
        session.query(UserAuthorization).filter(
            UserAuthorization.idUser.in_(ids)
        ).delete(synchronize_session=False)
        session.query(User).filter(User.id.in_(ids)).delete(synchronize_session=False)

    session_commit()


@pytest.fixture(scope="module", autouse=True)
def origin_users():
    """The origin users every test in this module runs as"""
    users = {
        "analyst": _create_origin_user(
            ANALYST_EMAIL, ANALYST_EXTERNAL, [Role.PRESCRIPTION_ANALYST.value]
        ),
        "viewer": _create_origin_user(
            VIEWER_EMAIL, VIEWER_EXTERNAL, [Role.VIEWER.value]
        ),
        "inactive": _create_origin_user(
            INACTIVE_EMAIL,
            INACTIVE_EXTERNAL,
            [Role.PRESCRIPTION_ANALYST.value],
            active=False,
        ),
        "foreign": _create_origin_user(
            FOREIGN_EMAIL,
            FOREIGN_EXTERNAL,
            [Role.PRESCRIPTION_ANALYST.value],
            schema="teste",
        ),
        "unauthorized": _create_origin_user(
            UNAUTHORIZED_EMAIL,
            UNAUTHORIZED_EXTERNAL,
            [Role.PRESCRIPTION_ANALYST.value],
            id_segment=None,
        ),
    }

    # ids are read here because the objects expire between tests
    ids = {key: user.id for key, user in users.items()}

    yield ids

    for email in TEST_EMAILS:
        _delete_origin_user(email)


@pytest.fixture
def integrator_headers(client):
    """Headers with SERVICE_INTEGRATOR role — the only role holding RUN_AS"""
    return make_headers(get_access(client, roles=[Role.SERVICE_INTEGRATOR.value]))


def test_static_check_sets_the_status_on_behalf_of_the_origin_user(
    client, integrator_headers, origin_users
):
    """POST /static/prescriptions/status - checa a prescrição em nome do usuário de origem"""
    id_prescription = create_basic_prescription().id

    response = client.post(
        STATIC_CHECK_URL, json=_payload(id_prescription), headers=integrator_headers
    )

    assert response.status_code == 200

    session.expire_all()
    prescription = (
        session.query(Prescription).filter(Prescription.id == id_prescription).first()
    )
    assert prescription.status == "s"
    # attributed to the origin user, never to the service integrator
    assert prescription.user == origin_users["analyst"]


def test_static_check_returns_the_checked_prescription(client, integrator_headers):
    """POST /static/prescriptions/status - devolve a prescrição checada"""
    id_prescription = create_basic_prescription().id

    response = client.post(
        STATIC_CHECK_URL, json=_payload(id_prescription), headers=integrator_headers
    )

    assert response.get_json()["data"] == [
        {"idPrescription": str(id_prescription), "status": "s"}
    ]


def test_static_check_audits_the_check_as_a_service_user(
    client, integrator_headers, origin_users
):
    """POST /static/prescriptions/status - registra a auditoria marcando a origem como serviço"""
    id_prescription = create_basic_prescription().id

    client.post(
        STATIC_CHECK_URL, json=_payload(id_prescription), headers=integrator_headers
    )

    session.expire_all()
    audit = (
        session.query(PrescriptionAudit)
        .filter(PrescriptionAudit.idPrescription == id_prescription)
        .filter(PrescriptionAudit.auditType == PrescriptionAuditTypeEnum.CHECK.value)
        .first()
    )

    assert audit is not None
    assert audit.createdBy == origin_users["analyst"]
    assert audit.extra["serviceUser"] is True


def test_static_check_undoes_a_previous_check(client, integrator_headers):
    """POST /static/prescriptions/status - desfaz a checagem quando o status enviado é 0"""
    id_prescription = create_basic_prescription().id

    client.post(
        STATIC_CHECK_URL, json=_payload(id_prescription), headers=integrator_headers
    )
    response = client.post(
        STATIC_CHECK_URL,
        json=_payload(id_prescription, status="0"),
        headers=integrator_headers,
    )

    assert response.status_code == 200

    session.expire_all()
    prescription = (
        session.query(Prescription).filter(Prescription.id == id_prescription).first()
    )
    assert prescription.status == "0"


def test_static_check_rejects_an_unknown_origin_user(client, integrator_headers):
    """POST /static/prescriptions/status - deve retornar erro [400] quando o id externo não existe"""
    id_prescription = create_basic_prescription().id

    response = client.post(
        STATIC_CHECK_URL,
        json=_payload(id_prescription, id_origin_user="ZZTEST-EXT-UNKNOWN"),
        headers=integrator_headers,
    )

    assert response.status_code == 400
    assert response.get_json()["message"] == "Usuário origem inválido"


def test_static_check_rejects_an_origin_user_without_segment_authorization(
    client, integrator_headers
):
    """POST /static/prescriptions/status - deve retornar erro [401 UNAUTHORIZED] quando o usuário de origem não tem o segmento autorizado"""
    id_prescription = create_basic_prescription().id

    response = client.post(
        STATIC_CHECK_URL,
        json=_payload(id_prescription, id_origin_user=UNAUTHORIZED_EXTERNAL),
        headers=integrator_headers,
    )

    assert response.status_code == 401
    assert response.get_json()["message"] == "Usuário não autorizado neste segmento"


def test_static_check_rejects_an_inactive_origin_user(client, integrator_headers):
    """POST /static/prescriptions/status - deve retornar erro [400] quando o usuário de origem está inativo"""
    id_prescription = create_basic_prescription().id

    response = client.post(
        STATIC_CHECK_URL,
        json=_payload(id_prescription, id_origin_user=INACTIVE_EXTERNAL),
        headers=integrator_headers,
    )

    assert response.status_code == 400
    assert response.get_json()["message"] == "Usuário origem inválido"


def test_static_check_rejects_an_origin_user_of_another_schema(
    client, integrator_headers
):
    """POST /static/prescriptions/status - deve retornar erro [400] quando o usuário de origem é de outro schema"""
    id_prescription = create_basic_prescription().id

    response = client.post(
        STATIC_CHECK_URL,
        json=_payload(id_prescription, id_origin_user=FOREIGN_EXTERNAL),
        headers=integrator_headers,
    )

    assert response.status_code == 400
    assert response.get_json()["message"] == "Usuário origem inválido"


def test_static_check_rejects_an_origin_user_without_write_permission(
    client, integrator_headers
):
    """POST /static/prescriptions/status - deve retornar erro [400] quando o usuário de origem não pode checar"""
    id_prescription = create_basic_prescription().id

    response = client.post(
        STATIC_CHECK_URL,
        json=_payload(id_prescription, id_origin_user=VIEWER_EXTERNAL),
        headers=integrator_headers,
    )

    assert response.status_code == 400
    assert (
        response.get_json()["message"]
        == "Usuário origem não possui permissão para checagem"
    )


def test_static_check_leaves_the_prescription_untouched_when_it_fails(
    client, integrator_headers
):
    """POST /static/prescriptions/status - não altera a prescrição quando o usuário de origem não pode checar"""
    id_prescription = create_basic_prescription().id

    client.post(
        STATIC_CHECK_URL,
        json=_payload(id_prescription, id_origin_user=VIEWER_EXTERNAL),
        headers=integrator_headers,
    )

    session.expire_all()
    prescription = (
        session.query(Prescription).filter(Prescription.id == id_prescription).first()
    )
    assert prescription.status == "0"


def test_static_check_rejects_an_unknown_prescription(client, integrator_headers):
    """POST /static/prescriptions/status - deve retornar erro [400] quando a prescrição não existe"""
    response = client.post(
        STATIC_CHECK_URL, json=_payload(999999999), headers=integrator_headers
    )

    assert response.status_code == 400
    assert response.get_json()["message"] == "Prescrição inexistente"


def test_static_check_rejects_a_status_that_does_not_change(client, integrator_headers):
    """POST /static/prescriptions/status - deve retornar erro [400] quando o status enviado não altera a prescrição"""
    id_prescription = create_basic_prescription().id

    client.post(
        STATIC_CHECK_URL, json=_payload(id_prescription), headers=integrator_headers
    )
    response = client.post(
        STATIC_CHECK_URL, json=_payload(id_prescription), headers=integrator_headers
    )

    assert response.status_code == 400
    assert "já está checada" in response.get_json()["message"]


def test_static_check_requires_the_run_as_permission(client, analyst_headers):
    """POST /static/prescriptions/status - deve retornar erro [401 UNAUTHORIZED] sem a permissão RUN_AS"""
    id_prescription = create_basic_prescription().id

    response = client.post(
        STATIC_CHECK_URL, json=_payload(id_prescription), headers=analyst_headers
    )

    assert response.status_code == 401


def test_static_check_requires_authentication(client):
    """POST /static/prescriptions/status - deve retornar erro [401 UNAUTHORIZED] sem autenticação"""
    response = client.post(STATIC_CHECK_URL, json=_payload(1))

    assert response.status_code == 401
