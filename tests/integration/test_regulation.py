"""Integration tests for the regulation ("regulação") endpoints.

The regulation module tracks external-care requests through a staged workflow.
``tests/unit/test_regulation_solicitation.py`` covers the service layer with a
mocked session; these tests run the same endpoints against the real database so
that ``repository/regulation/reg_solicitation_repository.py`` — the prioritization
query with its date/risk/stage/ICD filters, its ordering and its manual-record id
generators — is exercised for real.

The regulation tables carry no seed data, so the ``regulation_data`` fixture
builds a small work queue: three solicitations of two types, on three patients
with different birthdates and ICD codes.
"""

from datetime import datetime, timedelta

import pytest

from models.enums import RegulationAction
from models.regulation import (
    RegMovement,
    RegSolicitation,
    RegSolicitationAttribute,
)
from tests.conftest import session
from tests.utils import utils_test_regulation as utils

BASE_DATE = datetime(2024, 3, 10, 8, 0, 0)

TYPE_CONSULTATION = utils.TYPE_ID_BASE + 1
TYPE_EXAM = utils.TYPE_ID_BASE + 2

SOLICITATION_A = utils.SOLICITATION_ID_BASE + 1
SOLICITATION_B = utils.SOLICITATION_ID_BASE + 2
SOLICITATION_C = utils.SOLICITATION_ID_BASE + 3

ADMISSION_A = utils.ADMISSION_BASE + 1
ADMISSION_B = utils.ADMISSION_BASE + 2
ADMISSION_C = utils.ADMISSION_BASE + 3

PATIENT_A = utils.ADMISSION_BASE + 1
PATIENT_B = utils.ADMISSION_BASE + 2
PATIENT_C = utils.ADMISSION_BASE + 3

# C50 is listed in the ONCO group as an exact code; I109 is not listed anywhere,
# it only reaches CARDIOVASCULAR through that group's "I10%" wildcard — so the
# two branches of the repository's _icd_filter are both exercised below
ICD_ONCO = "C50"
ICD_CARDIO = "I109"


@pytest.fixture
def regulation_data():
    """Build the regulation work queue used by the tests and drop it afterwards."""
    utils.clean_regulation_data()

    user_id = utils.get_user_id()

    utils.create_solicitation_type(
        id=TYPE_CONSULTATION, name="ZZTEST Consulta", tp_type=1
    )
    utils.create_solicitation_type(id=TYPE_EXAM, name="ZZTEST Exame", tp_type=2)

    utils.create_icd(
        id_int=utils.ICD_ID_BASE + 1, id_str=ICD_ONCO, name="Neoplasia de teste"
    )
    utils.create_icd(
        id_int=utils.ICD_ID_BASE + 2, id_str=ICD_CARDIO, name="Hipertensao de teste"
    )

    utils.create_patient(
        admission_number=ADMISSION_A,
        id_patient=PATIENT_A,
        birthdate=datetime(1950, 1, 1),
        gender="M",
        id_icd=ICD_ONCO,
    )
    utils.create_patient(
        admission_number=ADMISSION_B,
        id_patient=PATIENT_B,
        birthdate=datetime(1990, 6, 15),
        gender="F",
        id_icd=ICD_CARDIO,
    )
    utils.create_patient(
        admission_number=ADMISSION_C,
        id_patient=PATIENT_C,
        birthdate=None,
        gender="M",
        id_icd=None,
    )

    utils.create_solicitation(
        id=SOLICITATION_A,
        admission_number=ADMISSION_A,
        id_patient=PATIENT_A,
        date=BASE_DATE,
        id_reg_solicitation_type=TYPE_CONSULTATION,
        id_department=1,
        risk=1,
        stage=0,
        created_by=user_id,
        cid=ICD_ONCO,
        attendant="Fulano Beltrano",
        attendant_record="ZZ-0001",
        justification="Justificativa de teste",
    )
    utils.create_solicitation(
        id=SOLICITATION_B,
        admission_number=ADMISSION_B,
        id_patient=PATIENT_B,
        date=BASE_DATE + timedelta(days=1),
        id_reg_solicitation_type=TYPE_EXAM,
        id_department=2,
        risk=3,
        stage=1,
        schedule_date=BASE_DATE + timedelta(days=5),
        transportation_date=BASE_DATE + timedelta(days=6),
        created_by=user_id,
    )
    utils.create_solicitation(
        id=SOLICITATION_C,
        admission_number=ADMISSION_C,
        id_patient=PATIENT_C,
        date=BASE_DATE + timedelta(days=2),
        id_reg_solicitation_type=TYPE_CONSULTATION,
        id_department=1,
        risk=None,
        stage=2,
    )

    yield

    utils.clean_regulation_data()


def _prioritization_body(**overrides):
    """Minimal valid prioritization request, covering the whole seeded window."""
    body = {
        "startDate": BASE_DATE.isoformat(),
        "endDate": (BASE_DATE + timedelta(days=30)).isoformat(),
        "limit": 50,
        "offset": 0,
        "order": [{"field": "date", "direction": "asc"}],
    }
    body.update(overrides)

    return body


def _ids(data):
    return [item["id"] for item in data["list"]]


# --- types -------------------------------------------------------------------


def test_get_types(client, regulator_headers, regulation_data):
    """GET /regulation/types lists the solicitation types by name [200 OK]."""
    response = client.get("/regulation/types", headers=regulator_headers)

    assert response.status_code == 200
    types = {t["id"]: t for t in response.get_json()["data"]}

    assert types[str(TYPE_CONSULTATION)]["name"] == "ZZTEST Consulta"
    assert types[str(TYPE_CONSULTATION)]["type"] == 1
    assert types[str(TYPE_EXAM)]["type"] == 2

    names = [t["name"] for t in response.get_json()["data"]]
    assert names == sorted(names)


def test_get_types_permission_denied(client, viewer_headers):
    """GET /regulation/types requires READ_REGULATION [401 UNAUTHORIZED]."""
    response = client.get("/regulation/types", headers=viewer_headers)

    assert response.status_code == 401


# --- prioritization ----------------------------------------------------------


def test_prioritization_list(client, regulator_headers, regulation_data):
    """POST /regulation/prioritization returns the queue with patient and type data."""
    response = client.post(
        "/regulation/prioritization",
        headers=regulator_headers,
        json=_prioritization_body(),
    )

    assert response.status_code == 200
    data = response.get_json()["data"]

    assert data["count"] == 3
    assert _ids(data) == [str(SOLICITATION_A), str(SOLICITATION_B), str(SOLICITATION_C)]

    first = data["list"][0]
    assert first["type"] == "ZZTEST Consulta"
    assert first["department"] == "Setor Adulto 1"
    assert first["stage"] == 0
    assert first["risk"] == 1
    assert first["idPatient"] == str(PATIENT_A)
    assert first["birthdate"].startswith("1950-01-01")
    assert first["age"] is not None

    # the patient without a birthdate still comes back, with a null age
    last = data["list"][2]
    assert last["birthdate"] is None
    assert last["age"] is None
    assert last["risk"] is None


def test_prioritization_date_range_excludes_outside(
    client, regulator_headers, regulation_data
):
    """The date range filters on the solicitation date, end date included."""
    response = client.post(
        "/regulation/prioritization",
        headers=regulator_headers,
        json=_prioritization_body(
            startDate=(BASE_DATE + timedelta(days=1)).isoformat(),
            endDate=(BASE_DATE + timedelta(days=1)).isoformat(),
        ),
    )

    assert response.status_code == 200
    assert _ids(response.get_json()["data"]) == [str(SOLICITATION_B)]


def test_prioritization_id_list_ignores_date_range(
    client, regulator_headers, regulation_data
):
    """idList selects solicitations directly, bypassing the date range."""
    response = client.post(
        "/regulation/prioritization",
        headers=regulator_headers,
        json=_prioritization_body(
            startDate=(BASE_DATE + timedelta(days=90)).isoformat(),
            endDate=(BASE_DATE + timedelta(days=95)).isoformat(),
            idList=[SOLICITATION_A, SOLICITATION_C],
        ),
    )

    assert response.status_code == 200
    assert sorted(_ids(response.get_json()["data"])) == sorted(
        [str(SOLICITATION_A), str(SOLICITATION_C)]
    )


@pytest.mark.parametrize(
    "filters,expected",
    [
        ({"riskList": [3]}, [SOLICITATION_B]),
        ({"stageList": [0, 2]}, [SOLICITATION_A, SOLICITATION_C]),
        ({"idDepartmentList": [2]}, [SOLICITATION_B]),
        ({"idPatientList": [PATIENT_B]}, [SOLICITATION_B]),
        ({"typeType": 2}, [SOLICITATION_B]),
        ({"typeList": [str(TYPE_CONSULTATION)]}, [SOLICITATION_A, SOLICITATION_C]),
        ({"idIcdList": [ICD_ONCO]}, [SOLICITATION_A]),
        ({"idIcdGroupList": ["ONCO"]}, [SOLICITATION_A]),
        ({"idIcdGroupList": ["CARDIOVASCULAR"]}, [SOLICITATION_B]),
        (
            {"idIcdGroupList": ["ONCO", "CARDIOVASCULAR"]},
            [SOLICITATION_A, SOLICITATION_B],
        ),
        (
            {"idIcdGroupList": ["UNKNOWN_GROUP"]},
            [SOLICITATION_A, SOLICITATION_B, SOLICITATION_C],
        ),
    ],
)
def test_prioritization_filters(
    client, regulator_headers, regulation_data, filters, expected
):
    """Each prioritization filter narrows the queue to the expected solicitations."""
    response = client.post(
        "/regulation/prioritization",
        headers=regulator_headers,
        json=_prioritization_body(**filters),
    )

    assert response.status_code == 200
    assert _ids(response.get_json()["data"]) == [str(i) for i in expected]


def test_prioritization_schedule_and_transportation_filters(
    client, regulator_headers, regulation_data
):
    """Schedule and transport date ranges only keep the scheduled solicitation."""
    scheduled = client.post(
        "/regulation/prioritization",
        headers=regulator_headers,
        json=_prioritization_body(
            scheduleStartDate=(BASE_DATE + timedelta(days=5)).isoformat(),
            scheduleEndDate=(BASE_DATE + timedelta(days=5)).isoformat(),
        ),
    )

    assert scheduled.status_code == 200
    assert _ids(scheduled.get_json()["data"]) == [str(SOLICITATION_B)]

    transported = client.post(
        "/regulation/prioritization",
        headers=regulator_headers,
        json=_prioritization_body(
            transportationStartDate=(BASE_DATE + timedelta(days=6)).isoformat(),
            transportationEndDate=(BASE_DATE + timedelta(days=6)).isoformat(),
        ),
    )

    assert transported.status_code == 200
    assert _ids(transported.get_json()["data"]) == [str(SOLICITATION_B)]


@pytest.mark.parametrize(
    "order,expected",
    [
        (
            {"field": "date", "direction": "desc"},
            [SOLICITATION_C, SOLICITATION_B, SOLICITATION_A],
        ),
        (
            {"field": "date_truncate", "direction": "asc"},
            [SOLICITATION_A, SOLICITATION_B, SOLICITATION_C],
        ),
        # nulls last: the solicitation without a risk closes the list
        (
            {"field": "risk", "direction": "desc"},
            [SOLICITATION_B, SOLICITATION_A, SOLICITATION_C],
        ),
        # birthdate is inverted on purpose: "desc" means oldest patient first
        (
            {"field": "birthdate", "direction": "desc"},
            [SOLICITATION_A, SOLICITATION_B, SOLICITATION_C],
        ),
    ],
)
def test_prioritization_ordering(
    client, regulator_headers, regulation_data, order, expected
):
    """Each supported sort field orders the queue, keeping null values last."""
    response = client.post(
        "/regulation/prioritization",
        headers=regulator_headers,
        json=_prioritization_body(order=[order]),
    )

    assert response.status_code == 200
    assert _ids(response.get_json()["data"]) == [str(i) for i in expected]


def test_prioritization_global_score(client, regulator_headers, regulation_data):
    """The global score comes from the patient's aggregated prescription."""
    utils.create_agg_prescription(
        id=8000001,
        admission_number=ADMISSION_B,
        id_patient=PATIENT_B,
        global_score=42,
    )

    response = client.post(
        "/regulation/prioritization",
        headers=regulator_headers,
        json=_prioritization_body(
            order=[{"field": "global_score", "direction": "desc"}]
        ),
    )

    assert response.status_code == 200
    data = response.get_json()["data"]

    scores = {item["id"]: item["globalScore"] for item in data["list"]}
    assert scores[str(SOLICITATION_B)] == 42
    # solicitations without an aggregated prescription have no score
    assert scores[str(SOLICITATION_A)] is None
    # nulls last, so the scored solicitation leads the queue
    assert data["list"][0]["id"] == str(SOLICITATION_B)


def test_prioritization_pagination(client, regulator_headers, regulation_data):
    """limit/offset page the queue while count keeps the full total."""
    response = client.post(
        "/regulation/prioritization",
        headers=regulator_headers,
        json=_prioritization_body(limit=1, offset=1),
    )

    assert response.status_code == 200
    data = response.get_json()["data"]

    assert data["count"] == 3
    assert _ids(data) == [str(SOLICITATION_B)]


def test_prioritization_empty_result(client, regulator_headers, regulation_data):
    """An empty queue returns a zero count instead of failing [200 OK]."""
    response = client.post(
        "/regulation/prioritization",
        headers=regulator_headers,
        json=_prioritization_body(idList=[SOLICITATION_A], stageList=[9]),
    )

    assert response.status_code == 200
    assert response.get_json()["data"] == {"count": 0, "list": []}


def test_prioritization_permission_denied(client, viewer_headers):
    """POST /regulation/prioritization requires READ_REGULATION [401 UNAUTHORIZED]."""
    response = client.post(
        "/regulation/prioritization",
        headers=viewer_headers,
        json=_prioritization_body(),
    )

    assert response.status_code == 401


# --- view --------------------------------------------------------------------


def test_view_solicitation(client, regulator_headers, regulation_data):
    """GET /regulation/view/<id> returns the solicitation with its initial event."""
    response = client.get(
        f"/regulation/view/{SOLICITATION_A}", headers=regulator_headers
    )

    assert response.status_code == 200
    data = response.get_json()["data"]

    assert data["id"] == str(SOLICITATION_A)
    assert data["admissionNumber"] == ADMISSION_A
    assert data["type"] == "ZZTEST Consulta"
    assert data["risk"] == 1
    assert data["attendant"] == "Fulano Beltrano"
    assert data["attendantRecord"] == "ZZ-0001"
    assert data["justification"] == "Justificativa de teste"
    assert data["cid"] == f"{ICD_ONCO} - Neoplasia de teste"
    assert data["patient"]["id"] == str(PATIENT_A)
    assert data["patient"]["gender"] == "M"

    # only the synthetic "created" event so far
    assert len(data["movements"]) == 1
    assert data["movements"][0]["action"] == -1
    assert data["movements"][0]["createdBy"] is not None


def test_view_solicitation_without_icd(client, regulator_headers, regulation_data):
    """A solicitation whose patient has no ICD comes back with a null cid."""
    response = client.get(
        f"/regulation/view/{SOLICITATION_C}", headers=regulator_headers
    )

    assert response.status_code == 200
    data = response.get_json()["data"]

    assert data["cid"] is None
    assert data["patient"]["birthdate"] is None
    # nobody is recorded as responsible for this one
    assert data["movements"][0]["createdBy"] is None


def test_view_invalid_solicitation(client, regulator_headers, regulation_data):
    """An unknown solicitation id is rejected [400 BAD REQUEST]."""
    response = client.get("/regulation/view/1", headers=regulator_headers)

    assert response.status_code == 400


def test_view_permission_denied(client, viewer_headers, regulation_data):
    """GET /regulation/view/<id> requires READ_REGULATION [401 UNAUTHORIZED]."""
    response = client.get(f"/regulation/view/{SOLICITATION_A}", headers=viewer_headers)

    assert response.status_code == 401


# --- move --------------------------------------------------------------------


def test_move_schedules_solicitation(client, regulator_headers, regulation_data):
    """A move records the movement, advances the stage and stores the dates."""
    response = client.post(
        "/regulation/move",
        headers=regulator_headers,
        json={
            "id": SOLICITATION_A,
            "action": RegulationAction.SCHEDULE.value,
            "nextStage": 3,
            "actionData": {
                "scheduleDate": "20/03/2024 10:30",
                "transportationDate": "21/03/2024 07:00",
                "reg_risk": 4,
                "reg_type": {"value": TYPE_EXAM, "label": "ZZTEST Exame"},
            },
            "actionDataTemplate": [{"field": "scheduleDate"}],
        },
    )

    assert response.status_code == 200
    result = response.get_json()["data"][0]

    assert result["id"] == str(SOLICITATION_A)
    assert result["stage"] == 3
    assert result["risk"] == 4
    assert result["extra"]["scheduleDate"].startswith("2024-03-20T10:30")
    assert result["extra"]["transportationDate"].startswith("2024-03-21T07:00")
    assert result["extra"]["regType"]["idRegSolicitationType"] == TYPE_EXAM
    # the movement history now holds the move plus the synthetic created event
    assert len(result["movements"]) == 2

    session.expire_all()
    stored = (
        session.query(RegSolicitation)
        .filter(RegSolicitation.id == SOLICITATION_A)
        .first()
    )
    assert stored.stage == 3
    assert stored.id_reg_solicitation_type == TYPE_EXAM
    assert stored.schedule_date == datetime(2024, 3, 20, 10, 30)

    movement = (
        session.query(RegMovement)
        .filter(RegMovement.id_reg_solicitation == SOLICITATION_A)
        .first()
    )
    assert movement.stage_origin == 0
    assert movement.stage_destination == 3
    assert movement.created_by is not None


def test_move_undo_clears_dates(client, regulator_headers, regulation_data):
    """The undo actions clear the schedule and the transport dates."""
    undo_schedule = client.post(
        "/regulation/move",
        headers=regulator_headers,
        json={
            "id": SOLICITATION_B,
            "action": RegulationAction.UNDO_SCHEDULE.value,
            "nextStage": 1,
            "actionData": {},
            "actionDataTemplate": [],
        },
    )

    assert undo_schedule.status_code == 200
    assert undo_schedule.get_json()["data"][0]["extra"]["scheduleDate"] is None

    undo_transportation = client.post(
        "/regulation/move",
        headers=regulator_headers,
        json={
            "id": SOLICITATION_B,
            "action": RegulationAction.UNDO_TRANSPORTATION_SCHEDULE.value,
            "nextStage": 1,
            "actionData": {},
            "actionDataTemplate": [],
        },
    )

    assert undo_transportation.status_code == 200
    extra = undo_transportation.get_json()["data"][0]["extra"]
    assert extra["transportationDate"] is None
    assert extra["regType"]["idRegSolicitationType"] is None


def test_move_multiple_solicitations(client, regulator_headers, regulation_data):
    """A batch move advances every solicitation and skips the movement history."""
    response = client.post(
        "/regulation/move",
        headers=regulator_headers,
        json={
            "ids": [SOLICITATION_A, SOLICITATION_C],
            "action": RegulationAction.SCHEDULE.value,
            "nextStage": 5,
            "actionData": {},
            "actionDataTemplate": [],
        },
    )

    assert response.status_code == 200
    results = response.get_json()["data"]

    assert [r["stage"] for r in results] == [5, 5]
    assert all(r["movements"] == [] for r in results)

    session.expire_all()
    stages = {
        s.id: s.stage
        for s in session.query(RegSolicitation)
        .filter(RegSolicitation.id.in_([SOLICITATION_A, SOLICITATION_C]))
        .all()
    }
    assert stages == {SOLICITATION_A: 5, SOLICITATION_C: 5}


def test_move_invalid_solicitation(client, regulator_headers, regulation_data):
    """Moving an unknown solicitation is rejected [400 BAD REQUEST]."""
    response = client.post(
        "/regulation/move",
        headers=regulator_headers,
        json={
            "id": 1,
            "action": RegulationAction.SCHEDULE.value,
            "nextStage": 1,
            "actionData": {},
            "actionDataTemplate": [],
        },
    )

    assert response.status_code == 400


def test_move_without_selection(client, regulator_headers, regulation_data):
    """A move without any solicitation selected is rejected [400 BAD REQUEST]."""
    response = client.post(
        "/regulation/move",
        headers=regulator_headers,
        json={
            "ids": [],
            "action": RegulationAction.SCHEDULE.value,
            "nextStage": 1,
            "actionData": {},
            "actionDataTemplate": [],
        },
    )

    assert response.status_code == 400


def test_move_permission_denied(
    client, regulator_headers, regulation_data, viewer_headers
):
    """POST /regulation/move requires WRITE_REGULATION [401 UNAUTHORIZED]."""
    response = client.post(
        "/regulation/move",
        headers=viewer_headers,
        json={
            "id": SOLICITATION_A,
            "action": RegulationAction.SCHEDULE.value,
            "nextStage": 1,
            "actionData": {},
            "actionDataTemplate": [],
        },
    )

    assert response.status_code == 401


# --- manual create -----------------------------------------------------------


def test_create_solicitation(client, regulator_headers, regulation_data):
    """POST /regulation/create adds the patient and one solicitation per type."""
    response = client.post(
        "/regulation/create",
        headers=regulator_headers,
        json={
            "idPatient": PATIENT_A,
            "birthdate": "1975-08-20",
            "idDepartment": 1,
            "solicitationDate": BASE_DATE.isoformat(),
            "idRegSolicitationTypeList": [TYPE_CONSULTATION, TYPE_EXAM],
            "risk": 2,
            "cid": ICD_CARDIO,
            "attendant": "Ciclano de Tal",
            "attendantRecord": "ZZ-0002",
            "justification": "Encaminhamento de teste",
        },
    )

    assert response.status_code == 200
    id_list = response.get_json()["data"]["idList"]

    assert len(id_list) == 2
    # manual records are numbered from their own reserved mask, consecutively
    assert int(id_list[0]) >= 9000000001
    assert int(id_list[1]) == int(id_list[0]) + 1

    created = (
        session.query(RegSolicitation)
        .filter(RegSolicitation.id.in_([int(i) for i in id_list]))
        .order_by(RegSolicitation.id)
        .all()
    )
    assert [s.id_reg_solicitation_type for s in created] == [
        TYPE_CONSULTATION,
        TYPE_EXAM,
    ]
    assert created[0].admission_number >= 90000000
    assert created[0].stage == 0
    assert created[0].risk == 2
    # both solicitations share the admission created for them
    assert created[0].admission_number == created[1].admission_number

    # and the new solicitations are readable through the regular endpoint
    view = client.get(f"/regulation/view/{id_list[0]}", headers=regulator_headers)
    assert view.status_code == 200
    assert view.get_json()["data"]["attendant"] == "Ciclano de Tal"


def test_create_permission_denied(client, viewer_headers):
    """POST /regulation/create requires WRITE_REGULATION [401 UNAUTHORIZED]."""
    response = client.post(
        "/regulation/create",
        headers=viewer_headers,
        json={
            "idPatient": PATIENT_A,
            "idDepartment": 1,
            "solicitationDate": BASE_DATE.isoformat(),
            "idRegSolicitationTypeList": [TYPE_CONSULTATION],
            "risk": 1,
            "justification": None,
        },
    )

    assert response.status_code == 401


# --- attributes --------------------------------------------------------------


def test_attribute_create_list_and_remove(client, regulator_headers, regulation_data):
    """Attributes are created, listed by type and soft-removed from the list."""
    created = client.post(
        "/regulation/attribute/create",
        headers=regulator_headers,
        json={
            "idRegSolicitation": SOLICITATION_A,
            "tpAttribute": 1,
            "tpStatus": 1,
            "value": {"note": "primeira anotacao"},
        },
    )

    assert created.status_code == 200
    attribute = created.get_json()["data"]
    assert attribute["tpAttribute"] == 1
    assert attribute["status"] == 1
    assert attribute["value"] == {"note": "primeira anotacao"}

    # an attribute of another type must not show up in the list below
    client.post(
        "/regulation/attribute/create",
        headers=regulator_headers,
        json={
            "idRegSolicitation": SOLICITATION_A,
            "tpAttribute": 2,
            "tpStatus": 1,
            "value": {"note": "outro tipo"},
        },
    )

    listed = client.get(
        f"/regulation/attribute/list?idRegSolicitation={SOLICITATION_A}&tpAttribute=1",
        headers=regulator_headers,
    )

    assert listed.status_code == 200
    data = listed.get_json()["data"]
    assert len(data) == 1
    assert data[0]["id"] == attribute["id"]
    assert data[0]["createdBy"] is not None

    removed = client.post(
        f"/regulation/attribute/remove/{attribute['id']}", headers=regulator_headers
    )

    assert removed.status_code == 200
    assert removed.get_json()["data"]["status"] == 2

    after_remove = client.get(
        f"/regulation/attribute/list?idRegSolicitation={SOLICITATION_A}&tpAttribute=1",
        headers=regulator_headers,
    )
    assert after_remove.get_json()["data"] == []

    # the row is kept, only its status changed (soft delete)
    session.expire_all()
    stored = (
        session.query(RegSolicitationAttribute)
        .filter(RegSolicitationAttribute.id == attribute["id"])
        .first()
    )
    assert stored is not None
    assert stored.tp_status == 2


def test_attribute_create_invalid_solicitation(
    client, regulator_headers, regulation_data
):
    """Creating an attribute for an unknown solicitation is rejected [400]."""
    response = client.post(
        "/regulation/attribute/create",
        headers=regulator_headers,
        json={
            "idRegSolicitation": 1,
            "tpAttribute": 1,
            "tpStatus": 1,
            "value": {"note": "x"},
        },
    )

    assert response.status_code == 400


def test_attribute_remove_invalid(client, regulator_headers, regulation_data):
    """Removing an unknown attribute is rejected [400 BAD REQUEST]."""
    response = client.post("/regulation/attribute/remove/1", headers=regulator_headers)

    assert response.status_code == 400


def test_attribute_list_permission_denied(client, viewer_headers, regulation_data):
    """GET /regulation/attribute/list requires READ_REGULATION [401]."""
    response = client.get(
        f"/regulation/attribute/list?idRegSolicitation={SOLICITATION_A}&tpAttribute=1",
        headers=viewer_headers,
    )

    assert response.status_code == 401
