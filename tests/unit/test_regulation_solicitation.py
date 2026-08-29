"""Unit tests for the regulation solicitation feature.

The regulation module tracks external-care requests ("solicitações") through a
staged workflow: a solicitation is created, then walked from stage to stage by
*movements* that also carry side effects (scheduling, transport scheduling,
type/risk changes and the corresponding undo actions).

Three services make up the feature:

* ``reg_solicitation_service`` — read one solicitation with its movement
  history, move one or many solicitations to a new stage, create solicitations
  manually (which also creates the patient/admission record);
* ``reg_solicitation_attribute_service`` — per-solicitation attributes, with a
  soft delete (``tp_status = 2``);
* ``reg_prioritization_service`` — the regulator work queue and the list of
  solicitation types.

The regulation tables live in a separate DDL file that neither CI nor the local
``make test-setup`` loads, so these are unit tests: ``db`` is replaced with a
mock session and the repository calls are patched. Real SQLAlchemy model
instances are still used as the rows, so column mapping and the services'
attribute writes are exercised for real. The ``@has_permission`` gate is
bypassed via ``__wrapped__`` except in the two tests that assert the gate
itself.
"""

from contextlib import contextmanager
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from exception.authorization_error import AuthorizationError
from exception.validation_error import ValidationError
from mobile import app
from models.enums import RegulationAction
from models.main import User
from models.prescription import Patient
from models.regulation import RegSolicitation, RegSolicitationAttribute
from models.requests.regulation_movement_request import RegulationMovementRequest
from models.requests.regulation_solicitation_attribute_request import (
    RegSolicitationAttributeListRequest,
    RegulationSolicitationAttributeRequest,
)
from models.requests.regulation_solicitation_request import (
    RegulationSolicitationRequest,
)
from security.role import Role
from services.regulation import (
    reg_prioritization_service,
    reg_solicitation_attribute_service,
    reg_solicitation_service,
)

# Undecorated business logic (skips the permission gate).
_get_solicitation = reg_solicitation_service.get_solicitation.__wrapped__
_move = reg_solicitation_service.move.__wrapped__
_create = reg_solicitation_service.create.__wrapped__
_attribute_create = reg_solicitation_attribute_service.create.__wrapped__
_attribute_remove = reg_solicitation_attribute_service.remove.__wrapped__
_get_attributes = reg_solicitation_attribute_service.get_attributes.__wrapped__
_get_prioritization = reg_prioritization_service.get_prioritization.__wrapped__
_get_types = reg_prioritization_service.get_types.__wrapped__


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _user(id=7, name="Regulador"):
    """Build a User row usable as ``user_context`` / movement responsible."""
    user = User()
    user.id = id
    user.name = name
    return user


def _solicitation(
    *,
    id=9000000001,
    admission_number=90000001,
    id_patient=55,
    stage=1,
    risk=3,
    schedule_date=None,
    transportation_date=None,
    id_type=4,
):
    """Build a RegSolicitation row in a known state."""
    solicitation = RegSolicitation()
    solicitation.id = id
    solicitation.admission_number = admission_number
    solicitation.id_patient = id_patient
    solicitation.date = datetime(2026, 3, 1, 8, 30)
    solicitation.id_reg_solicitation_type = id_type
    solicitation.id_department = 12
    solicitation.risk = risk
    solicitation.cid = "C50"
    solicitation.attendant = "Atendente Um"
    solicitation.attendant_record = "REG-1"
    solicitation.justification = "encaminhamento"
    solicitation.stage = stage
    solicitation.schedule_date = schedule_date
    solicitation.transportation_date = transportation_date
    return solicitation


def _mock_db():
    """A mock ``db`` whose session records ``add`` calls."""
    mock_db = MagicMock()
    mock_db.session.added = []
    mock_db.session.add.side_effect = mock_db.session.added.append
    return mock_db


def _movement_row(*, id=1, origin=0, destination=1, action=1, responsible=None):
    """Build a (RegMovement, User) repository row for the movement history."""
    reg_movement = SimpleNamespace(
        id=id,
        stage_origin=origin,
        stage_destination=destination,
        action=action,
        data={"note": "ok"},
        template=[{"label": "Nota"}],
        created_at=datetime(2026, 3, 2, 10, 0),
    )
    return SimpleNamespace(RegMovement=reg_movement, User=responsible)


def _movement_request(**overrides):
    """Build a RegulationMovementRequest with sensible defaults."""
    payload = {
        "id": 9000000001,
        "action": RegulationAction.UPDATE_STAGE.value,
        "actionData": {},
        "actionDataTemplate": [],
        "nextStage": 2,
    }
    payload.update(overrides)
    return RegulationMovementRequest(**payload)


@contextmanager
def acting_as(roles):
    """Run the block inside a request context authenticated as ``roles``.

    Patches the permission decorator's JWT identity lookup and ``User`` model
    so the decorated service resolves a fabricated user carrying ``roles``.
    """
    fake_user = MagicMock()
    fake_user.id = 7
    fake_user.config = {"roles": roles}
    with app.test_request_context():
        with patch(
            "decorators.has_permission_decorator.get_jwt_identity", return_value=1
        ), patch("decorators.has_permission_decorator.User") as mock_user_cls:
            mock_user_cls.find.return_value = fake_user
            yield


# --------------------------------------------------------------------------
# get_solicitation — read one solicitation with its movement history
# --------------------------------------------------------------------------


def test_get_solicitation_unknown_id_is_rejected():
    """An id with no matching row raises a 400 ValidationError."""
    repo = reg_solicitation_service.reg_solicitation_repository
    with patch.object(repo, "get_solicitation", return_value=None):
        with pytest.raises(ValidationError) as exc:
            _get_solicitation(id=404)

    assert exc.value.code == "errors.invalidRecord"
    assert exc.value.httpStatus == 400


def test_get_solicitation_maps_the_full_payload():
    """Every solicitation, type, patient and ICD field is mapped for the UI."""
    solicitation = _solicitation(
        schedule_date=datetime(2026, 4, 1, 14, 0),
        transportation_date=datetime(2026, 4, 1, 12, 0),
    )
    row = SimpleNamespace(
        RegSolicitation=solicitation,
        RegSolicitationType=SimpleNamespace(name="Consulta"),
        Patient=SimpleNamespace(birthdate=date(1980, 5, 4), gender="M"),
        ICDTable=SimpleNamespace(id_str="C50", name="Neoplasia da mama"),
        User=_user(name="Solicitante"),
    )

    repo = reg_solicitation_service.reg_solicitation_repository
    with patch.object(repo, "get_solicitation", return_value=row), patch.object(
        repo, "get_solicitation_movement", return_value=[]
    ):
        result = _get_solicitation(id=solicitation.id)

    # ids are stringified so large BigInteger values survive JSON transport
    assert result["id"] == "9000000001"
    assert result["admissionNumber"] == 90000001
    assert result["stage"] == 1
    assert result["date"] == "2026-03-01T08:30:00"
    assert result["type"] == "Consulta"
    assert result["idRegSolicitationType"] == 4
    assert result["risk"] == 3
    assert result["attendant"] == "Atendente Um"
    assert result["attendantRecord"] == "REG-1"
    assert result["cid"] == "C50 - Neoplasia da mama"
    assert result["justification"] == "encaminhamento"
    assert result["patient"] == {
        "id": "55",
        "birthdate": "1980-05-04",
        "gender": "M",
    }
    assert result["extra"] == {
        "scheduleDate": "2026-04-01T14:00:00",
        "transportationDate": "2026-04-01T12:00:00",
    }


def test_get_solicitation_tolerates_missing_joins():
    """Missing type/patient/ICD/responsible rows map to nulls, not errors."""
    row = SimpleNamespace(
        RegSolicitation=_solicitation(),
        RegSolicitationType=None,
        Patient=None,
        ICDTable=None,
        User=None,
    )

    repo = reg_solicitation_service.reg_solicitation_repository
    with patch.object(repo, "get_solicitation", return_value=row), patch.object(
        repo, "get_solicitation_movement", return_value=[]
    ):
        result = _get_solicitation(id=1)

    assert result["type"] is None
    assert result["cid"] is None
    assert result["patient"] == {"id": "55", "birthdate": None, "gender": None}
    assert result["extra"] == {"scheduleDate": None, "transportationDate": None}
    # only the synthetic initial event, with no responsible name
    assert [m["id"] for m in result["movements"]] == ["0"]
    assert result["movements"][0]["createdBy"] is None


def test_get_solicitation_appends_the_initial_event_to_the_history():
    """Stored movements are mapped, then a synthetic creation event is added."""
    solicitation = _solicitation()
    row = SimpleNamespace(
        RegSolicitation=solicitation,
        RegSolicitationType=None,
        Patient=None,
        ICDTable=None,
        User=_user(name="Solicitante"),
    )
    records = [
        _movement_row(id=20, origin=1, destination=2, responsible=_user(name="Ana")),
        _movement_row(id=10, origin=0, destination=1, responsible=None),
    ]

    repo = reg_solicitation_service.reg_solicitation_repository
    with patch.object(repo, "get_solicitation", return_value=row), patch.object(
        repo, "get_solicitation_movement", return_value=records
    ) as get_movements:
        result = _get_solicitation(id=solicitation.id)

    get_movements.assert_called_once_with(id_reg_solicitation=solicitation.id)

    movements = result["movements"]
    # repository order is preserved and the initial event always comes last
    assert [m["id"] for m in movements] == ["20", "10", "0"]
    assert movements[0]["origin"] == 1
    assert movements[0]["destination"] == 2
    assert movements[0]["data"] == {"note": "ok"}
    assert movements[0]["template"] == [{"label": "Nota"}]
    assert movements[0]["createdAt"] == "2026-03-02T10:00:00"
    assert movements[0]["createdBy"] == "Ana"
    assert movements[1]["createdBy"] is None

    # the initial event is marked with action -1 and the solicitation's own date
    initial = movements[-1]
    assert initial["action"] == -1
    assert initial["origin"] is None
    assert initial["destination"] is None
    assert initial["createdAt"] == "2026-03-01T08:30:00"
    assert initial["createdBy"] == "Solicitante"


# --------------------------------------------------------------------------
# move — walk a solicitation to the next stage
# --------------------------------------------------------------------------


def _run_move(request_data, solicitations):
    """Invoke ``move`` with ``db`` mocked to return ``solicitations`` in order.

    Returns ``(result, mock_db)`` so callers can inspect the added movements.
    """
    mock_db = _mock_db()
    query = mock_db.session.query.return_value.filter.return_value
    query.first.side_effect = list(solicitations)

    with patch.object(reg_solicitation_service, "db", mock_db), patch.object(
        reg_solicitation_service.reg_solicitation_repository,
        "get_solicitation_movement",
        return_value=[],
    ):
        result = _move(request_data=request_data, user_context=_user())

    return result, mock_db


def test_move_without_any_id_is_rejected():
    """Neither ``id`` nor ``ids`` given: nothing to move, so 400."""
    request_data = _movement_request(id=None, ids=None)

    with pytest.raises(ValidationError) as exc:
        _move(request_data=request_data, user_context=_user())

    assert exc.value.code == "errors.invalidParams"
    assert exc.value.httpStatus == 400


def test_move_with_empty_ids_list_is_rejected():
    """An explicitly empty ``ids`` list is rejected the same way."""
    request_data = _movement_request(id=None, ids=[])

    with pytest.raises(ValidationError) as exc:
        _move(request_data=request_data, user_context=_user())

    assert exc.value.code == "errors.invalidParams"


def test_move_unknown_solicitation_is_rejected():
    """An id that resolves to no row raises a 400 ValidationError."""
    with pytest.raises(ValidationError) as exc:
        _run_move(_movement_request(), [None])

    assert exc.value.code == "errors.invalidRecord"


def test_move_records_the_movement_and_advances_the_stage():
    """The new movement captures the origin stage before the update lands."""
    solicitation = _solicitation(stage=1)
    request_data = _movement_request(
        nextStage=2,
        action=RegulationAction.UPDATE_STAGE.value,
        actionData={"note": "ok"},
        actionDataTemplate=[{"label": "Nota"}],
    )

    result, mock_db = _run_move(request_data, [solicitation])

    movement = mock_db.session.added[0]
    assert movement.id_reg_solicitation == solicitation.id
    assert movement.stage_origin == 1
    assert movement.stage_destination == 2
    assert movement.action == RegulationAction.UPDATE_STAGE.value
    assert movement.data == {"note": "ok"}
    assert movement.template == [{"label": "Nota"}]
    assert movement.created_by == 7

    assert solicitation.stage == 2
    assert result[0]["id"] == "9000000001"
    assert result[0]["stage"] == 2


def test_move_parses_the_schedule_date_from_the_action_data():
    """``scheduleDate`` arrives as dd/mm/yyyy hh:mm and is stored as datetime."""
    solicitation = _solicitation(stage=1)
    request_data = _movement_request(
        action=RegulationAction.SCHEDULE.value,
        actionData={"scheduleDate": "15/04/2026 09:45"},
    )

    result, _ = _run_move(request_data, [solicitation])

    assert solicitation.schedule_date == datetime(2026, 4, 15, 9, 45)
    assert result[0]["extra"]["scheduleDate"] == "2026-04-15T09:45:00"


def test_move_parses_the_transportation_date_from_the_action_data():
    """``transportationDate`` is parsed with the same dd/mm/yyyy hh:mm mask."""
    solicitation = _solicitation(stage=1)
    request_data = _movement_request(
        action=RegulationAction.SCHEDULE_TRANSPORT.value,
        actionData={"transportationDate": "15/04/2026 07:10"},
    )

    result, _ = _run_move(request_data, [solicitation])

    assert solicitation.transportation_date == datetime(2026, 4, 15, 7, 10)
    assert result[0]["extra"]["transportationDate"] == "2026-04-15T07:10:00"


def test_move_updates_the_solicitation_type():
    """A ``reg_type`` payload retargets the type and is echoed back to the UI."""
    solicitation = _solicitation(id_type=4)
    request_data = _movement_request(
        action=RegulationAction.UPDATE_TYPE.value,
        actionData={"reg_type": {"value": 9, "label": "Exame"}},
    )

    result, _ = _run_move(request_data, [solicitation])

    assert solicitation.id_reg_solicitation_type == 9
    assert result[0]["extra"]["regType"] == {
        "type": "Exame",
        "idRegSolicitationType": 9,
    }


def test_move_ignores_a_null_solicitation_type():
    """``reg_type: None`` clears the UI echo without touching the stored type."""
    solicitation = _solicitation(id_type=4)
    request_data = _movement_request(
        action=RegulationAction.UPDATE_TYPE.value,
        actionData={"reg_type": None},
    )

    result, _ = _run_move(request_data, [solicitation])

    assert solicitation.id_reg_solicitation_type == 4
    assert result[0]["extra"]["regType"] == {
        "type": None,
        "idRegSolicitationType": None,
    }


def test_move_updates_the_risk():
    """``reg_risk`` overwrites the solicitation risk and is returned."""
    solicitation = _solicitation(risk=3)
    request_data = _movement_request(
        action=RegulationAction.UPDATE_RISK.value,
        actionData={"reg_risk": 1},
    )

    result, _ = _run_move(request_data, [solicitation])

    assert solicitation.risk == 1
    assert result[0]["risk"] == 1


def test_move_undo_schedule_clears_the_schedule_date():
    """The UNDO_SCHEDULE action wins over any date in the payload."""
    solicitation = _solicitation(schedule_date=datetime(2026, 4, 1, 14, 0))
    request_data = _movement_request(
        action=RegulationAction.UNDO_SCHEDULE.value,
        actionData={"scheduleDate": "15/04/2026 09:45"},
    )

    result, _ = _run_move(request_data, [solicitation])

    assert solicitation.schedule_date is None
    assert result[0]["extra"]["scheduleDate"] is None


def test_move_undo_transportation_clears_the_transportation_date():
    """UNDO_TRANSPORTATION_SCHEDULE clears the transport date the same way."""
    solicitation = _solicitation(transportation_date=datetime(2026, 4, 1, 12, 0))
    request_data = _movement_request(
        action=RegulationAction.UNDO_TRANSPORTATION_SCHEDULE.value,
        actionData={"transportationDate": "15/04/2026 07:10"},
    )

    result, _ = _run_move(request_data, [solicitation])

    assert solicitation.transportation_date is None
    assert result[0]["extra"]["transportationDate"] is None


def test_move_single_id_returns_the_movement_history():
    """Moving exactly one solicitation returns its refreshed history."""
    solicitation = _solicitation()
    result, _ = _run_move(_movement_request(), [solicitation])

    # the synthetic initial event is always present
    assert [m["id"] for m in result[0]["movements"]] == ["0"]


def test_move_batch_moves_every_solicitation_and_omits_the_history():
    """A batch move updates each row; histories are dropped from the payload."""
    first = _solicitation(id=9000000001, stage=1)
    second = _solicitation(id=9000000002, stage=1)
    request_data = _movement_request(id=None, ids=[first.id, second.id], nextStage=3)

    result, mock_db = _run_move(request_data, [first, second])

    assert first.stage == 3
    assert second.stage == 3
    assert [r["id"] for r in result] == ["9000000001", "9000000002"]
    # histories are expensive and unused for batches
    assert all(r["movements"] == [] for r in result)
    # one movement recorded per solicitation
    assert len(mock_db.session.added) == 2


def test_move_batch_rejects_the_whole_request_on_an_unknown_id():
    """An invalid id anywhere in the batch aborts before commit."""
    first = _solicitation(id=9000000001)
    request_data = _movement_request(id=None, ids=[first.id, 404])

    with pytest.raises(ValidationError) as exc:
        _run_move(request_data, [first, None])

    assert exc.value.code == "errors.invalidRecord"


def test_move_prefers_the_single_id_over_the_ids_list():
    """When both are sent, ``id`` wins and ``ids`` is ignored."""
    solicitation = _solicitation(id=9000000001)
    request_data = _movement_request(id=solicitation.id, ids=[1, 2, 3])

    result, mock_db = _run_move(request_data, [solicitation])

    assert [r["id"] for r in result] == ["9000000001"]
    assert len(mock_db.session.added) == 1


# --------------------------------------------------------------------------
# create — manually register a solicitation (and its admission)
# --------------------------------------------------------------------------


def _solicitation_request(**overrides):
    """Build a RegulationSolicitationRequest with sensible defaults."""
    payload = {
        "idPatient": 55,
        "birthdate": date(1980, 5, 4),
        "idDepartment": 12,
        "solicitationDate": datetime(2026, 3, 1, 8, 30),
        "idRegSolicitationTypeList": [4],
        "risk": 3,
        "cid": "C50",
        "attendant": "Atendente Um",
        "attendantRecord": "REG-1",
        "justification": "encaminhamento",
    }
    payload.update(overrides)
    return RegulationSolicitationRequest(**payload)


def _run_create(request_data, *, next_id=9000000001, next_admission=90000001):
    """Invoke ``create`` with ``db`` and the id generators patched."""
    mock_db = _mock_db()
    repo = reg_solicitation_service.reg_solicitation_repository

    with patch.object(reg_solicitation_service, "db", mock_db), patch.object(
        repo, "get_next_admission_number", return_value=next_admission
    ), patch.object(
        repo,
        "get_next_solicitation_id",
        side_effect=[next_id + i for i in range(10)],
    ):
        result = _create(request_data=request_data, user_context=_user())

    return result, mock_db


def test_create_registers_the_patient_and_one_solicitation_per_type():
    """One admission is created, then a solicitation for each requested type."""
    request_data = _solicitation_request(idRegSolicitationTypeList=[4, 9])

    result, mock_db = _run_create(request_data)

    added = mock_db.session.added
    patient = added[0]
    assert isinstance(patient, Patient)
    assert patient.idPatient == 55
    assert patient.idHospital == 1
    assert patient.birthdate == date(1980, 5, 4)
    assert patient.admissionNumber == 90000001
    assert patient.user == 7

    solicitations = added[1:]
    assert [s.id_reg_solicitation_type for s in solicitations] == [4, 9]
    assert result == {"idList": ["9000000001", "9000000002"]}


def test_create_copies_the_request_fields_onto_the_solicitation():
    """Clinical/administrative fields are persisted as sent."""
    _, mock_db = _run_create(_solicitation_request())

    solicitation = mock_db.session.added[1]
    assert isinstance(solicitation, RegSolicitation)
    assert solicitation.admission_number == 90000001
    assert solicitation.id_patient == 55
    assert solicitation.date == datetime(2026, 3, 1, 8, 30)
    assert solicitation.id_department == 12
    assert solicitation.risk == 3
    assert solicitation.cid == "C50"
    assert solicitation.attendant == "Atendente Um"
    assert solicitation.attendant_record == "REG-1"
    assert solicitation.justification == "encaminhamento"
    # a manual solicitation always enters the workflow at the first stage
    assert solicitation.stage == 0
    assert solicitation.created_by == 7


def test_create_without_any_type_still_registers_the_admission():
    """An empty type list creates the patient but no solicitation."""
    request_data = _solicitation_request(idRegSolicitationTypeList=[])

    result, mock_db = _run_create(request_data)

    assert result == {"idList": []}
    assert len(mock_db.session.added) == 1
    assert isinstance(mock_db.session.added[0], Patient)


def test_create_accepts_a_patient_without_a_birthdate():
    """``birthdate`` is optional; the admission is created with a null one."""
    result, mock_db = _run_create(_solicitation_request(birthdate=None))

    assert mock_db.session.added[0].birthdate is None
    assert result["idList"] == ["9000000001"]


# --------------------------------------------------------------------------
# solicitation attributes
# --------------------------------------------------------------------------


def _attribute(*, id=1, tp_attribute=2, tp_status=1, value=None):
    """Build a RegSolicitationAttribute row."""
    attribute = RegSolicitationAttribute()
    attribute.id = id
    attribute.id_reg_solicitation = 9000000001
    attribute.tp_attribute = tp_attribute
    attribute.tp_status = tp_status
    attribute.value = {"text": "obs"} if value is None else value
    attribute.created_at = datetime(2026, 3, 2, 10, 0)
    attribute.created_by = 7
    return attribute


def _run_attribute(fn, *, first, **kwargs):
    """Invoke an attribute service function with ``db`` mocked."""
    mock_db = _mock_db()
    mock_db.session.query.return_value.filter.return_value.first.return_value = first

    with patch.object(reg_solicitation_attribute_service, "db", mock_db):
        result = fn(**kwargs)

    return result, mock_db


def test_attribute_create_requires_an_existing_solicitation():
    """Attaching an attribute to an unknown solicitation raises a 400."""
    request_data = RegulationSolicitationAttributeRequest(
        idRegSolicitation=404, tpAttribute=2, tpStatus=1, value={"text": "obs"}
    )

    with pytest.raises(ValidationError) as exc:
        _run_attribute(
            _attribute_create,
            first=None,
            request_data=request_data,
            user_context=_user(),
        )

    assert exc.value.code == "errors.invalidRecord"
    assert exc.value.httpStatus == 400


def test_attribute_create_stores_an_active_attribute():
    """A new attribute is always created active, whatever status was sent."""
    solicitation = _solicitation()
    request_data = RegulationSolicitationAttributeRequest(
        idRegSolicitation=solicitation.id,
        tpAttribute=2,
        # the client-sent status is deliberately ignored by the service
        tpStatus=99,
        value={"text": "obs"},
    )

    result, mock_db = _run_attribute(
        _attribute_create,
        first=solicitation,
        request_data=request_data,
        user_context=_user(),
    )

    stored = mock_db.session.added[0]
    assert stored.id_reg_solicitation == solicitation.id
    assert stored.tp_attribute == 2
    assert stored.tp_status == 1
    assert stored.value == {"text": "obs"}
    assert stored.created_by == 7

    assert result["tpAttribute"] == 2
    assert result["status"] == 1
    assert result["value"] == {"text": "obs"}


def test_attribute_remove_unknown_id_is_rejected():
    """Removing an attribute that does not exist raises a 400."""
    with pytest.raises(ValidationError) as exc:
        _run_attribute(
            _attribute_remove,
            first=None,
            idreg_solicitation_attribute=404,
            user_context=_user(),
        )

    assert exc.value.code == "errors.invalidRecord"


def test_attribute_remove_is_a_soft_delete():
    """Removal flips the status to 2 and stamps the responsible user."""
    attribute = _attribute(tp_status=1)

    result, _ = _run_attribute(
        _attribute_remove,
        first=attribute,
        idreg_solicitation_attribute=attribute.id,
        user_context=_user(),
    )

    assert attribute.tp_status == 2
    assert attribute.updated_by == 7
    assert attribute.updated_at is not None
    assert result["status"] == 2
    assert result["createdAt"] == "2026-03-02T10:00:00"


def test_get_attributes_maps_the_rows_with_the_author_name():
    """Listing returns the attribute fields plus the joined author name."""
    rows = [
        SimpleNamespace(
            RegSolicitationAttribute=_attribute(id=1, value={"text": "primeira"}),
            createdByName="Ana",
        ),
        SimpleNamespace(
            RegSolicitationAttribute=_attribute(id=2, value={"text": "segunda"}),
            createdByName=None,
        ),
    ]
    mock_db = _mock_db()
    (
        mock_db.session.query.return_value.outerjoin.return_value.filter.return_value.filter.return_value.filter.return_value.order_by.return_value.all.return_value
    ) = rows

    request_data = RegSolicitationAttributeListRequest(
        idRegSolicitation=9000000001, tpAttribute=2
    )
    with patch.object(reg_solicitation_attribute_service, "db", mock_db):
        result = _get_attributes(request_data=request_data)

    assert [r["id"] for r in result] == [1, 2]
    assert result[0]["value"] == {"text": "primeira"}
    assert result[0]["createdBy"] == "Ana"
    assert result[0]["createdAt"] == "2026-03-02T10:00:00"
    assert result[1]["createdBy"] is None


def test_get_attributes_empty_list():
    """No matching attributes yields an empty list, not an error."""
    mock_db = _mock_db()
    (
        mock_db.session.query.return_value.outerjoin.return_value.filter.return_value.filter.return_value.filter.return_value.order_by.return_value.all.return_value
    ) = []

    request_data = RegSolicitationAttributeListRequest(
        idRegSolicitation=9000000001, tpAttribute=2
    )
    with patch.object(reg_solicitation_attribute_service, "db", mock_db):
        assert _get_attributes(request_data=request_data) == []


# --------------------------------------------------------------------------
# prioritization — the regulator work queue
# --------------------------------------------------------------------------


def _prioritization_row(
    *,
    id=9000000001,
    total=2,
    global_score=17,
    type_name="Consulta",
    department_name="Oncologia",
    birthdate=date(1980, 5, 4),
):
    """Build a prioritization repository row."""
    return SimpleNamespace(
        RegSolicitation=_solicitation(id=id),
        RegSolicitationType=SimpleNamespace(name=type_name)
        if type_name is not None
        else None,
        Patient=SimpleNamespace(birthdate=birthdate) if birthdate is not None else None,
        Department=SimpleNamespace(name=department_name)
        if department_name is not None
        else None,
        total=total,
        global_score=global_score,
    )


def test_get_prioritization_empty_queue():
    """With no results the count is zero and the list is empty."""
    repo = reg_prioritization_service.reg_solicitation_repository
    with patch.object(repo, "get_prioritization", return_value=[]):
        result = _get_prioritization(request_data=MagicMock())

    assert result == {"count": 0, "list": []}


def test_get_prioritization_maps_rows_and_reads_the_count_from_the_window():
    """The total comes from the window function, not from the page length.

    The query is paginated, so the window ``total`` (every matching
    solicitation) is deliberately larger than the number of rows returned —
    the UI needs it to render the pager.
    """
    rows = [
        _prioritization_row(id=9000000001, total=57, global_score=17),
        _prioritization_row(id=9000000002, total=57, global_score=None),
    ]

    repo = reg_prioritization_service.reg_solicitation_repository
    with patch.object(repo, "get_prioritization", return_value=rows):
        result = _get_prioritization(request_data=MagicMock())

    assert result["count"] == 57
    assert [r["id"] for r in result["list"]] == ["9000000001", "9000000002"]

    first = result["list"][0]
    assert first["date"] == "2026-03-01T08:30:00"
    assert first["idPatient"] == "55"
    assert first["idDepartment"] == "12"
    assert first["department"] == "Oncologia"
    assert first["stage"] == 1
    assert first["risk"] == 3
    assert first["idRegSolicitationType"] == "4"
    assert first["type"] == "Consulta"
    assert first["birthdate"] == "1980-05-04"
    assert first["globalScore"] == 17
    assert result["list"][1]["globalScore"] is None


def test_get_prioritization_computes_the_patient_age():
    """Age is derived from the birthdate, in whole years."""
    born = date(2000, 1, 1)
    rows = [_prioritization_row(birthdate=born)]

    repo = reg_prioritization_service.reg_solicitation_repository
    with patch.object(repo, "get_prioritization", return_value=rows):
        result = _get_prioritization(request_data=MagicMock())

    expected = int((datetime.today() - datetime(2000, 1, 1)).days / 365.2425)
    assert result["list"][0]["age"] == expected


def test_get_prioritization_tolerates_missing_joins():
    """Rows with no type/patient/department map to nulls instead of failing."""
    rows = [_prioritization_row(type_name=None, department_name=None, birthdate=None)]

    repo = reg_prioritization_service.reg_solicitation_repository
    with patch.object(repo, "get_prioritization", return_value=rows):
        result = _get_prioritization(request_data=MagicMock())

    record = result["list"][0]
    assert record["type"] is None
    assert record["department"] is None
    assert record["birthdate"] is None
    assert record["age"] is None


def test_get_prioritization_handles_a_patient_without_a_birthdate():
    """A patient row with a null birthdate yields a null age."""
    rows = [_prioritization_row()]
    rows[0].Patient = SimpleNamespace(birthdate=None)

    repo = reg_prioritization_service.reg_solicitation_repository
    with patch.object(repo, "get_prioritization", return_value=rows):
        result = _get_prioritization(request_data=MagicMock())

    assert result["list"][0]["birthdate"] is None
    assert result["list"][0]["age"] is None


def test_get_types_maps_id_name_and_type():
    """Solicitation types are returned with stringified ids."""
    rows = [
        SimpleNamespace(id=4, name="Consulta", tp_type=1),
        SimpleNamespace(id=9, name="Exame", tp_type=2),
    ]

    repo = reg_prioritization_service.reg_solicitation_repository
    with patch.object(repo, "get_types", return_value=rows):
        result = _get_types()

    assert result == [
        {"id": "4", "name": "Consulta", "type": 1},
        {"id": "9", "name": "Exame", "type": 2},
    ]


# --------------------------------------------------------------------------
# permission gate
# --------------------------------------------------------------------------


def test_read_requires_the_read_regulation_permission():
    """A role without READ_REGULATION cannot read a solicitation."""
    with acting_as([Role.DISPENSING_MANAGER.value]):
        with pytest.raises(AuthorizationError):
            reg_solicitation_service.get_solicitation(id=1)


def test_write_requires_the_write_regulation_permission():
    """READ_REGULATION alone is not enough to move a solicitation.

    NAVIGATOR carries READ_REGULATION but not WRITE_REGULATION.
    """
    with acting_as([Role.NAVIGATOR.value]):
        with pytest.raises(AuthorizationError):
            reg_solicitation_service.move(request_data=_movement_request())


def test_regulator_role_passes_the_gate():
    """REGULATOR carries both regulation permissions, so the gate lets it in."""
    repo = reg_solicitation_service.reg_solicitation_repository
    with acting_as([Role.REGULATOR.value]):
        with patch.object(repo, "get_solicitation", return_value=None):
            # reaching the service body (invalid record) proves the gate passed
            with pytest.raises(ValidationError) as exc:
                reg_solicitation_service.get_solicitation(id=404)

    assert exc.value.code == "errors.invalidRecord"
