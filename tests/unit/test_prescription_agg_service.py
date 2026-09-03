"""Unit tests for the prescription-aggregation (prescalc) service.

NoHarm's work queue is built on *aggregated prescriptions* — one synthetic
"prescription-day" row per admission/segment/date that rolls up every
individual prescription the hospital sent for that day. ``prescalc`` is the
pipeline that keeps those rows in sync, and it is entered two ways:

* ``create_agg_prescription_by_prescription`` — one individual prescription
  arrived (the classic flow);
* ``create_agg_prescription_by_date`` — an admission/date pair changed (the
  CPOE flow, where items carry their own validity period).

Both share the delicate parts: an advisory lock that serializes concurrent runs
for the same admission, an idempotency check so an already-processed
prescription is not recomputed, the ``gen_agg_id`` derivation, the score
variation against the previous day, and — most consequential clinically —
deciding whether a pharmacist's *check* survives the recalculation or has to be
withdrawn because the item list changed underneath it.

These are unit tests. ``db`` is replaced with a fake session (``query()`` walks
a queue of rows, ``add()`` is recorded) and every collaborating service and
repository is patched, so each branch can be driven directly without the
regulation/CPOE fixtures the integration suite would need. Real SQLAlchemy
model instances are used as the rows, so the services' attribute writes are
exercised for real.
"""

import json
from contextlib import ExitStack, contextmanager
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from exception.validation_error import ValidationError
from models.enums import (
    DrugTypeEnum,
    PatientConciliationStatusEnum,
    PrescriptionAuditTypeEnum,
    PrescriptionDrugAuditTypeEnum,
)
from models.main import User
from models.prescription import Patient, Prescription, PrescriptionAudit
from services import prescription_agg_service
from utils import prescriptionutils

# Undecorated business logic (skips the permission gate).
_create_by_prescription = (
    prescription_agg_service.create_agg_prescription_by_prescription.__wrapped__
)
_create_by_date = prescription_agg_service.create_agg_prescription_by_date.__wrapped__

SCHEMA = "demo"
ADMISSION = 100001


# --------------------------------------------------------------------------
# fakes
# --------------------------------------------------------------------------


class _FakeQuery:
    """Query stub: any filter/order chain resolves to the next queued row."""

    def __init__(self, queue):
        self._queue = queue

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return self._queue.pop(0) if self._queue else None


def _fake_db(rows=()):
    """Build a fake ``db``: ``query().…first()`` pops ``rows`` in order.

    ``session.added`` records everything handed to ``session.add`` so tests can
    assert on the inserted agg prescriptions and audit rows.
    """
    fake_db = MagicMock()
    fake_db.session.added = []
    fake_db.session.add.side_effect = fake_db.session.added.append

    queue = list(rows)
    fake_db.session.query.side_effect = lambda *a, **k: _FakeQuery(queue)
    fake_db.session.row_queue = queue

    return fake_db


def _user(id=1, schema=SCHEMA):
    """Build the ``user_context`` the service passes down to the view layer."""
    user = User()
    user.id = id
    user.schema = schema
    return user


def _prescription(
    *,
    id=100100,
    admission_number=ADMISSION,
    id_patient=55,
    id_segment=1,
    p_date=None,
    status=0,
    concilia=None,
    features=None,
    id_department=7,
):
    """Build an individual Prescription row in a known state."""
    prescription = Prescription()
    prescription.id = id
    prescription.admissionNumber = admission_number
    prescription.idPatient = id_patient
    prescription.idSegment = id_segment
    prescription.idHospital = 1
    prescription.idDepartment = id_department
    prescription.date = p_date if p_date is not None else datetime(2026, 3, 10, 8, 0)
    prescription.status = status
    prescription.concilia = concilia
    prescription.features = features
    prescription.bed = "101-A"
    prescription.record = "REC-1"
    prescription.specialty = "Clínica Médica"
    prescription.insurance = "SUS"
    return prescription


def _features(**overrides):
    """Build the feature payload ``prescriptionutils.getFeatures`` returns."""
    features = {
        "drugIDs": [11, 22],
        "departmentList": [7],
        "globalScore": 40,
        "totalItens": 3,
    }
    features.update(overrides)
    return features


DEFAULT_VARIATION = {
    "variation": 100,
    "currentGlobalScore": 40,
    "previousGlobalScore": 0,
}


@contextmanager
def prescalc_env(
    *,
    rows=(),
    features=None,
    lock_acquired=True,
    processed_status="NEW_PRESCRIPTION",
    is_cpoe=False,
    out_patient=False,
    drug_count=1,
    last_check_data=None,
    has_feature=False,
    outpatient_processed_status="PENDING",
    internal_prescription_ids=(100100,),
):
    """Patch every prescalc collaborator and yield the mocks under test.

    Only the service's own decision logic is left real: the fake ``db``, the
    repository lookups, the view/feature helpers and the check service are all
    controlled from here so each branch can be reached deterministically.
    """
    fake_db = _fake_db(rows)
    features = _features() if features is None else features
    mocks = SimpleNamespace(db=fake_db)

    module = prescription_agg_service
    with ExitStack() as stack:
        p = stack.enter_context

        p(patch.object(module, "db", fake_db))
        p(patch.object(module, "_set_schema"))
        mocks.logger = p(patch.object(module.logger, "backend_logger"))

        mocks.acquire_lock = p(
            patch.object(
                module.prescalc_repository,
                "acquire_admission_lock",
                return_value=lock_acquired,
            )
        )
        mocks.get_processed_status = p(
            patch.object(
                module.prescalc_repository,
                "get_processed_status",
                return_value=processed_status,
            )
        )
        mocks.get_processed_outpatient_status = p(
            patch.object(
                module.prescalc_repository,
                "get_processed_outpatient_status",
                return_value=outpatient_processed_status,
            )
        )
        mocks.get_last_check_data = p(
            patch.object(
                module.prescalc_repository,
                "get_last_check_data",
                return_value=last_check_data,
            )
        )

        mocks.is_cpoe = p(
            patch.object(module.segment_service, "is_cpoe", return_value=is_cpoe)
        )
        mocks.has_feature_nouser = p(
            patch.object(
                module.memory_service, "has_feature_nouser", return_value=out_patient
            )
        )
        mocks.has_feature = p(
            patch.object(
                module.feature_service, "has_feature", return_value=has_feature
            )
        )
        mocks.static_get_prescription = p(
            patch.object(
                module.prescription_view_service,
                "static_get_prescription",
                return_value={"data": "irrelevant"},
            )
        )
        mocks.get_features = p(
            patch.object(
                module.prescriptionutils, "getFeatures", return_value=features
            )
        )
        mocks.get_internal_prescription_ids = p(
            patch.object(
                module.prescriptionutils,
                "get_internal_prescription_ids",
                return_value=list(internal_prescription_ids),
            )
        )
        mocks.count_drugs = p(
            patch.object(
                module.prescription_drug_service,
                "count_drugs_by_prescription",
                return_value=drug_count,
            )
        )
        mocks.audit_check = p(
            patch.object(module.prescription_check_service, "audit_check")
        )
        mocks.check_prescription = p(
            patch.object(module.prescription_check_service, "check_prescription")
        )

        mocks.score_variation = p(
            patch.object(
                module, "_get_score_variation", return_value=dict(DEFAULT_VARIATION)
            )
        )
        mocks.log_processed_date = p(patch.object(module, "_log_processed_date"))
        mocks.update_conciliation = p(
            patch.object(module, "_update_patient_conciliation_status")
        )

        yield mocks


def _logged_events(mock_logger):
    """Collect the JSON log payloads the service emitted."""
    events = []
    for call in mock_logger.warning.call_args_list:
        if not call.args:
            continue
        try:
            events.append(json.loads(call.args[0]))
        except (TypeError, ValueError):
            continue
    return events


def _added(mocks, model):
    """Return the rows of ``model`` handed to ``session.add``."""
    return [row for row in mocks.db.session.added if isinstance(row, model)]


# --------------------------------------------------------------------------
# create_agg_prescription_by_prescription — guards
# --------------------------------------------------------------------------


def test_by_prescription_unknown_id_is_rejected():
    """An id with no matching prescription raises a 400 ValidationError."""
    with prescalc_env(rows=[None]):
        with pytest.raises(ValidationError) as exc:
            _create_by_prescription(
                schema=SCHEMA, id_prescription=404, user_context=_user()
            )

    assert exc.value.code == "errors.invalidPrescription"
    assert exc.value.httpStatus == 400


def test_by_prescription_without_a_segment_is_skipped():
    """A prescription the integration has not segmented yet cannot be rolled up."""
    prescription = _prescription(id_segment=None)

    with prescalc_env(rows=[prescription]) as mocks:
        result = _create_by_prescription(
            schema=SCHEMA, id_prescription=prescription.id, user_context=_user()
        )

    assert result is None
    # bailing out before the lock keeps the admission free for the real flow
    mocks.acquire_lock.assert_not_called()


def test_by_prescription_rejects_a_cpoe_segment():
    """CPOE admissions must go through the by-date entry point instead."""
    prescription = _prescription()

    with prescalc_env(rows=[prescription], is_cpoe=True):
        with pytest.raises(ValidationError) as exc:
            _create_by_prescription(
                schema=SCHEMA, id_prescription=prescription.id, user_context=_user()
            )

    assert exc.value.code == "errors.businessRules"


def test_by_prescription_allows_a_conciliation_on_a_cpoe_segment():
    """Conciliations are the documented exception to the CPOE rule."""
    prescription = _prescription(concilia="s")

    with prescalc_env(rows=[prescription], is_cpoe=True) as mocks:
        _create_by_prescription(
            schema=SCHEMA, id_prescription=prescription.id, user_context=_user()
        )

    assert prescription.features == _features()
    mocks.acquire_lock.assert_called_once()


# --------------------------------------------------------------------------
# create_agg_prescription_by_prescription — concurrency and idempotency
# --------------------------------------------------------------------------


def test_by_prescription_skips_when_the_admission_lock_is_held():
    """A concurrent prescalc run for the same admission wins; this one skips.

    Items stay unmarked, so the next prescalc event reprocesses them as
    NEW_ITENS — nothing is lost by giving up here.
    """
    prescription = _prescription()

    with prescalc_env(rows=[prescription], lock_acquired=False) as mocks:
        result = _create_by_prescription(
            schema=SCHEMA, id_prescription=prescription.id, user_context=_user()
        )

    assert result is None
    mocks.static_get_prescription.assert_not_called()
    mocks.log_processed_date.assert_not_called()

    events = _logged_events(mocks.logger)
    assert [e["event"] for e in events] == ["prescalc_lock_timeout"]
    assert events[0]["admission_number"] == ADMISSION
    assert events[0]["id_prescription"] == prescription.id


def test_by_prescription_locks_on_the_admission_copied_before_the_call():
    """The lock key is read off the row first: a timeout expires the instance."""
    prescription = _prescription()

    with prescalc_env(rows=[prescription], lock_acquired=False) as mocks:
        _create_by_prescription(
            schema=SCHEMA, id_prescription=prescription.id, user_context=_user()
        )

    mocks.acquire_lock.assert_called_once_with(
        schema=SCHEMA, admission_number=ADMISSION
    )


def test_by_prescription_skips_an_already_processed_prescription():
    """Idempotency: processed items with computed features are not redone."""
    prescription = _prescription(features=_features())

    with prescalc_env(
        rows=[prescription], processed_status="PROCESSED"
    ) as mocks:
        result = _create_by_prescription(
            schema=SCHEMA, id_prescription=prescription.id, user_context=_user()
        )

    assert result is None
    mocks.static_get_prescription.assert_not_called()
    assert [e["message"] for e in _logged_events(mocks.logger)] == [
        "Prescrição já foi processada"
    ]


def test_by_prescription_force_reprocesses_an_already_processed_prescription():
    """``force`` is the support escape hatch for a bad earlier calculation."""
    prescription = _prescription(features=_features())

    with prescalc_env(
        rows=[prescription, None], processed_status="PROCESSED"
    ) as mocks:
        _create_by_prescription(
            schema=SCHEMA,
            id_prescription=prescription.id,
            user_context=_user(),
            force=True,
        )

    assert mocks.static_get_prescription.called
    mocks.log_processed_date.assert_called_once()


def test_by_prescription_reprocesses_when_features_were_never_computed():
    """A PROCESSED row with no features is a failed run, so it is redone."""
    prescription = _prescription(features=None)

    with prescalc_env(
        rows=[prescription, None], processed_status="PROCESSED"
    ) as mocks:
        _create_by_prescription(
            schema=SCHEMA, id_prescription=prescription.id, user_context=_user()
        )

    assert mocks.static_get_prescription.called


# --------------------------------------------------------------------------
# create_agg_prescription_by_prescription — conciliation short-circuit
# --------------------------------------------------------------------------


def test_by_prescription_conciliation_updates_itself_and_stops():
    """A conciliation carries its own features and never joins an agg row."""
    prescription = _prescription(concilia="s")

    with prescalc_env(rows=[prescription]) as mocks:
        result = _create_by_prescription(
            schema=SCHEMA, id_prescription=prescription.id, user_context=_user()
        )

    assert result is None
    assert prescription.features == _features()
    assert prescription.aggDrugs == [11, 22]
    assert prescription.aggDeps == [prescription.idDepartment]

    # no agg prescription and no audit row were created
    assert mocks.db.session.added == []
    mocks.log_processed_date.assert_not_called()
    mocks.db.session.flush.assert_called_once()


def test_by_prescription_marks_the_conciliation_on_the_patient():
    """The patient's conciliation status is advanced for a conciliation row."""
    prescription = _prescription(concilia="s")

    with prescalc_env(rows=[prescription]) as mocks:
        _create_by_prescription(
            schema=SCHEMA, id_prescription=prescription.id, user_context=_user()
        )

    mocks.update_conciliation.assert_called_once_with(
        admission_number=ADMISSION, is_concilia=True
    )


# --------------------------------------------------------------------------
# create_agg_prescription_by_prescription — building the agg prescription
# --------------------------------------------------------------------------


def test_by_prescription_creates_the_agg_prescription_with_the_derived_id():
    """A missing agg row is inserted under the id ``gen_agg_id`` derives."""
    prescription = _prescription(p_date=datetime(2026, 3, 10, 8, 0))
    expected_id = prescriptionutils.gen_agg_id(
        prescription.admissionNumber, prescription.idSegment, prescription.date
    )

    with prescalc_env(rows=[prescription, None]) as mocks:
        _create_by_prescription(
            schema=SCHEMA, id_prescription=prescription.id, user_context=_user()
        )

    agg = _added(mocks, Prescription)[0]
    assert agg.id == expected_id
    assert agg.admissionNumber == ADMISSION
    assert agg.idPatient == prescription.idPatient
    assert agg.date == prescription.date
    assert agg.agg is True
    assert agg.prescriber == "Prescrição Agregada"
    # the header fields are mirrored from the individual prescription
    assert agg.idSegment == prescription.idSegment
    assert agg.idDepartment == prescription.idDepartment
    assert agg.bed == prescription.bed
    assert agg.record == prescription.record
    assert agg.specialty == prescription.specialty
    assert agg.insurance == prescription.insurance


def test_by_prescription_audits_a_newly_created_agg_prescription():
    """The insert is recorded as a CREATE_AGG audit event."""
    prescription = _prescription()

    with prescalc_env(rows=[prescription, None]) as mocks:
        _create_by_prescription(
            schema=SCHEMA, id_prescription=prescription.id, user_context=_user()
        )

    audits = _added(mocks, PrescriptionAudit)
    assert len(audits) == 1
    assert audits[0].auditType == PrescriptionAuditTypeEnum.CREATE_AGG.value
    assert audits[0].admissionNumber == ADMISSION
    assert audits[0].createdBy == 0


def test_by_prescription_reuses_an_existing_agg_prescription():
    """A second prescription for the same day updates the existing row."""
    prescription = _prescription()
    existing_agg = _prescription(id=999, status=0)

    with prescalc_env(rows=[prescription, existing_agg]) as mocks:
        _create_by_prescription(
            schema=SCHEMA, id_prescription=prescription.id, user_context=_user()
        )

    # nothing inserted: neither a prescription nor a CREATE_AGG audit
    assert mocks.db.session.added == []
    assert existing_agg.features["scoreVariation"] == DEFAULT_VARIATION


def test_by_prescription_stores_the_features_and_score_variation():
    """The agg row carries the rolled-up features plus the day-over-day delta."""
    prescription = _prescription()
    features = _features(drugIDs=[3, 4], departmentList=[7, 9])

    with prescalc_env(rows=[prescription, None], features=features) as mocks:
        _create_by_prescription(
            schema=SCHEMA, id_prescription=prescription.id, user_context=_user()
        )

    agg = _added(mocks, Prescription)[0]
    assert agg.features["scoreVariation"] == DEFAULT_VARIATION
    assert agg.aggDrugs == [3, 4]
    assert agg.aggDeps == [7, 9]

    # intervals are resolved against the agg date for this flow
    _, kwargs = mocks.get_features.call_args
    assert kwargs["agg_date"] == agg.date
    assert kwargs["intervals_for_agg_date"] is True


def test_by_prescription_marks_the_items_as_processed():
    """The run ends by stamping PROCESSED on the prescription's items."""
    prescription = _prescription()

    with prescalc_env(rows=[prescription, None]) as mocks:
        _create_by_prescription(
            schema=SCHEMA, id_prescription=prescription.id, user_context=_user()
        )

    mocks.log_processed_date.assert_called_once_with(
        id_prescription_array=[prescription.id], schema=SCHEMA
    )


# --------------------------------------------------------------------------
# create_agg_prescription_by_prescription — which day the items land on
# --------------------------------------------------------------------------


def test_new_items_on_a_recent_prescription_land_on_today():
    """Items added to yesterday's prescription belong to today's work queue."""
    yesterday = datetime.today() - timedelta(days=1)
    prescription = _prescription(p_date=yesterday)

    with prescalc_env(rows=[prescription, None], processed_status="NEW_ITENS") as mocks:
        _create_by_prescription(
            schema=SCHEMA, id_prescription=prescription.id, user_context=_user()
        )

    agg = _added(mocks, Prescription)[0]
    assert agg.date == datetime.today().date()


def test_new_items_on_an_older_prescription_keep_the_original_date():
    """A backfill for an old prescription must not pollute today's queue."""
    prescription = _prescription(p_date=datetime.today() - timedelta(days=5))

    with prescalc_env(rows=[prescription, None], processed_status="NEW_ITENS") as mocks:
        _create_by_prescription(
            schema=SCHEMA, id_prescription=prescription.id, user_context=_user()
        )

    agg = _added(mocks, Prescription)[0]
    assert agg.date == prescription.date


def test_a_new_prescription_always_keeps_its_own_date():
    """The today-shift only applies to NEW_ITENS, not to a first calculation."""
    prescription = _prescription(p_date=datetime.today() - timedelta(days=1))

    with prescalc_env(
        rows=[prescription, None], processed_status="NEW_PRESCRIPTION"
    ) as mocks:
        _create_by_prescription(
            schema=SCHEMA, id_prescription=prescription.id, user_context=_user()
        )

    agg = _added(mocks, Prescription)[0]
    assert agg.date == prescription.date


def test_primary_care_aggregates_per_admission_instead_of_per_day():
    """Outpatient tenants keep one agg row per admission, keyed by its number."""
    prescription = _prescription(p_date=datetime(2026, 3, 10, 8, 0))

    with prescalc_env(rows=[prescription, None], out_patient=True) as mocks:
        _create_by_prescription(
            schema=SCHEMA, id_prescription=prescription.id, user_context=_user()
        )

    agg = _added(mocks, Prescription)[0]
    assert agg.id == ADMISSION
    # the timestamp is truncated to a plain date for this flow
    assert agg.date == date(2026, 3, 10)


# --------------------------------------------------------------------------
# create_agg_prescription_by_prescription — the pharmacist's check
# --------------------------------------------------------------------------


def test_a_changed_item_count_withdraws_the_check_from_both_rows():
    """New items invalidate the review, so both checks are withdrawn.

    This is the clinically important branch: a pharmacist checked the
    prescription, then items changed, so the check must not stand.
    """
    prescription = _prescription(status="s")
    existing_agg = _prescription(id=999, status="s")
    last_check = SimpleNamespace(PrescriptionAudit=SimpleNamespace(totalItens=2))

    with prescalc_env(
        rows=[prescription, existing_agg],
        drug_count=5,
        last_check_data=last_check,
    ) as mocks:
        _create_by_prescription(
            schema=SCHEMA, id_prescription=prescription.id, user_context=_user()
        )

    assert existing_agg.status == 0
    assert prescription.status == 0
    assert prescription.user is None

    audited = [call.kwargs["prescription"] for call in mocks.audit_check.call_args_list]
    assert audited == [existing_agg, prescription]
    # the audit is attributed to the prescalc service user, not a person
    assert all(call.kwargs["user"].id == 0 for call in mocks.audit_check.call_args_list)
    assert mocks.audit_check.call_args_list[0].kwargs["extra"]["prescalc"] is True


def test_an_unchanged_item_count_keeps_the_existing_check():
    """Recalculating the same items must not undo a pharmacist's review."""
    prescription = _prescription(status="s")
    existing_agg = _prescription(id=999, status="s")
    last_check = SimpleNamespace(PrescriptionAudit=SimpleNamespace(totalItens=3))

    with prescalc_env(
        rows=[prescription, existing_agg],
        drug_count=3,
        last_check_data=last_check,
    ) as mocks:
        _create_by_prescription(
            schema=SCHEMA, id_prescription=prescription.id, user_context=_user()
        )

    assert existing_agg.status == "s"
    assert prescription.status == "s"
    mocks.audit_check.assert_not_called()


def test_a_new_agg_prescription_inherits_an_unchanged_check():
    """A first agg row for an already-checked prescription starts checked.

    The DB trigger inserts it as unchecked, so the service writes the status
    back explicitly.
    """
    prescription = _prescription(status="s")
    last_check = SimpleNamespace(PrescriptionAudit=SimpleNamespace(totalItens=3))

    with prescalc_env(
        rows=[prescription, None], drug_count=3, last_check_data=last_check
    ) as mocks:
        _create_by_prescription(
            schema=SCHEMA, id_prescription=prescription.id, user_context=_user()
        )

    agg = _added(mocks, Prescription)[0]
    assert agg.status == "s"
    assert prescription.status == "s"

    extra = mocks.audit_check.call_args.kwargs["extra"]
    assert extra["is_new_prescription"] is True
    assert extra["prescalc_source"] == prescription.id


def test_no_check_is_touched_when_the_prescription_has_no_validated_items():
    """Diets and materials alone do not carry a check to withdraw."""
    prescription = _prescription(status="s")
    existing_agg = _prescription(id=999, status="s")

    with prescalc_env(
        rows=[prescription, existing_agg], drug_count=0
    ) as mocks:
        _create_by_prescription(
            schema=SCHEMA, id_prescription=prescription.id, user_context=_user()
        )

    assert existing_agg.status == "s"
    assert prescription.status == "s"
    mocks.audit_check.assert_not_called()


def test_the_check_count_ignores_diets_and_materials():
    """Only drugs, solutions and procedures are validated by a pharmacist."""
    prescription = _prescription(status="s")

    with prescalc_env(rows=[prescription, None]) as mocks:
        _create_by_prescription(
            schema=SCHEMA, id_prescription=prescription.id, user_context=_user()
        )

    drug_types = mocks.count_drugs.call_args.kwargs["drug_types"]
    assert drug_types == [
        DrugTypeEnum.DRUG.value,
        DrugTypeEnum.PROCEDURE.value,
        DrugTypeEnum.SOLUTION.value,
    ]
    assert DrugTypeEnum.DIET.value not in drug_types
    assert DrugTypeEnum.MATERIAL.value not in drug_types


def test_a_checked_agg_row_is_withdrawn_when_new_items_arrive():
    """An unchecked prescription with new items still unchecks the agg row."""
    prescription = _prescription(status=0)
    existing_agg = _prescription(id=999, status="s")

    with prescalc_env(
        rows=[prescription, existing_agg], processed_status="NEW_ITENS"
    ) as mocks:
        _create_by_prescription(
            schema=SCHEMA, id_prescription=prescription.id, user_context=_user()
        )

    assert existing_agg.status == 0
    assert prescription.status == 0
    audited = [call.kwargs["prescription"] for call in mocks.audit_check.call_args_list]
    assert audited == [existing_agg]


def test_a_checked_agg_row_survives_a_reprocessed_prescription():
    """A forced recalculation of processed items leaves the agg check alone."""
    prescription = _prescription(status=0, features=_features())
    existing_agg = _prescription(id=999, status="s")

    with prescalc_env(
        rows=[prescription, existing_agg], processed_status="PROCESSED"
    ) as mocks:
        _create_by_prescription(
            schema=SCHEMA,
            id_prescription=prescription.id,
            user_context=_user(),
            force=True,
        )

    assert existing_agg.status == "s"
    mocks.audit_check.assert_not_called()


# --------------------------------------------------------------------------
# create_agg_prescription_by_date (CPOE)
# --------------------------------------------------------------------------


def _by_date_rows(existing=None, reloaded=None):
    """Queue the two rows ``create_agg_prescription_by_date`` reads.

    The flow looks the agg prescription up, then re-reads it after
    ``session.expire`` to pick up what the insert trigger wrote. ``existing``
    is the first lookup (``None`` when the row has to be created) and
    ``reloaded`` is what the second one returns.
    """
    return [existing, reloaded if reloaded is not None else _prescription(id=999)]


@contextmanager
def _by_date_env(last_prescription, **kwargs):
    """Run ``prescalc_env`` with the last-prescription lookup patched."""
    with prescalc_env(**kwargs) as mocks:
        with patch.object(
            prescription_agg_service.prescription_repository,
            "get_last_prescription",
            return_value=last_prescription,
        ) as get_last:
            mocks.get_last_prescription = get_last
            yield mocks


def test_by_date_prefers_an_existing_agg_prescription_as_the_template():
    """The agg row is looked up first; the individual one is the fallback."""
    last = _prescription(id=888)

    with _by_date_env(last, rows=_by_date_rows()) as mocks:
        _create_by_date(
            schema=SCHEMA,
            admission_number=ADMISSION,
            p_date=date(2026, 3, 10),
            user_context=_user(),
        )

    assert mocks.get_last_prescription.call_args_list[0].kwargs == {
        "admission_number": ADMISSION,
        "cpoe": True,
        "agg": True,
    }


def test_by_date_falls_back_to_the_last_individual_prescription():
    """With no agg row yet, the newest individual prescription is the template."""
    individual = _prescription(id=777)

    with prescalc_env(rows=_by_date_rows()) as mocks:
        with patch.object(
            prescription_agg_service.prescription_repository,
            "get_last_prescription",
            side_effect=[None, individual],
        ) as get_last:
            _create_by_date(
                schema=SCHEMA,
                admission_number=ADMISSION,
                p_date=date(2026, 3, 10),
                user_context=_user(),
            )

    assert get_last.call_args_list[1].kwargs["agg"] is False
    agg = _added(mocks, Prescription)[0]
    assert agg.idPatient == individual.idPatient


def test_by_date_skips_an_admission_with_no_prescription():
    """Nothing to aggregate: log the reason and give up without locking."""
    with _by_date_env(None, rows=[]) as mocks:
        result = _create_by_date(
            schema=SCHEMA,
            admission_number=ADMISSION,
            p_date=date(2026, 3, 10),
            user_context=_user(),
        )

    assert result is None
    mocks.acquire_lock.assert_not_called()
    assert _logged_events(mocks.logger)[0]["message"] == (
        "Não foi possível encontrar o segmento deste atendimento"
    )


def test_by_date_skips_a_template_without_a_segment():
    """A prescription the integration has not segmented cannot seed an agg row."""
    with _by_date_env(_prescription(id_segment=None), rows=[]) as mocks:
        result = _create_by_date(
            schema=SCHEMA,
            admission_number=ADMISSION,
            p_date=date(2026, 3, 10),
            user_context=_user(),
        )

    assert result is None
    mocks.acquire_lock.assert_not_called()


def test_by_date_skips_when_the_admission_lock_is_held():
    """Same serialization guarantee as the by-prescription entry point."""
    with _by_date_env(_prescription(), rows=[], lock_acquired=False) as mocks:
        result = _create_by_date(
            schema=SCHEMA,
            admission_number=ADMISSION,
            p_date=date(2026, 3, 10),
            user_context=_user(),
        )

    assert result is None
    mocks.static_get_prescription.assert_not_called()
    assert [e["event"] for e in _logged_events(mocks.logger)] == [
        "prescalc_lock_timeout"
    ]


def test_by_date_creates_the_agg_prescription_with_the_derived_id():
    """The row is inserted under ``gen_agg_id`` and audited as CREATE_AGG."""
    last = _prescription(id=888)
    p_date = date(2026, 3, 10)
    expected_id = prescriptionutils.gen_agg_id(ADMISSION, last.idSegment, p_date)

    with _by_date_env(last, rows=_by_date_rows()) as mocks:
        _create_by_date(
            schema=SCHEMA,
            admission_number=ADMISSION,
            p_date=p_date,
            user_context=_user(),
        )

    agg = _added(mocks, Prescription)[0]
    assert agg.id == expected_id
    assert agg.date == p_date
    assert agg.agg is True
    assert agg.prescriber == "Prescrição Agregada"

    audits = _added(mocks, PrescriptionAudit)
    assert [a.auditType for a in audits] == [
        PrescriptionAuditTypeEnum.CREATE_AGG.value
    ]


def test_by_date_reuses_an_existing_agg_prescription():
    """A recalculation of the same day updates the row instead of inserting."""
    existing = _prescription(id=999)

    with _by_date_env(
        _prescription(id=888), rows=_by_date_rows(existing, existing)
    ) as mocks:
        _create_by_date(
            schema=SCHEMA,
            admission_number=ADMISSION,
            p_date=date(2026, 3, 10),
            user_context=_user(),
        )

    assert mocks.db.session.added == []
    assert existing.features["scoreVariation"] == DEFAULT_VARIATION
    # CPOE items carry their own period, so intervals are not re-anchored
    assert mocks.get_features.call_args.kwargs["intervals_for_agg_date"] is False
    assert existing.features["should_update"] is False


def test_by_date_restores_a_segment_cleared_by_the_trigger():
    """The insert trigger can null the segment; the service writes it back."""
    reloaded = _prescription(id=999, id_segment=None)

    with _by_date_env(
        _prescription(id=888, id_segment=4), rows=_by_date_rows(reloaded=reloaded)
    ):
        _create_by_date(
            schema=SCHEMA,
            admission_number=ADMISSION,
            p_date=date(2026, 3, 10),
            user_context=_user(),
        )

    assert reloaded.idSegment == 4


def test_by_date_skips_a_processed_outpatient_admission():
    """With the outpatient flag on, an already-processed day is rolled back."""
    with _by_date_env(
        _prescription(id=888),
        rows=[None],
        has_feature=True,
        outpatient_processed_status="PROCESSED",
    ) as mocks:
        result = _create_by_date(
            schema=SCHEMA,
            admission_number=ADMISSION,
            p_date=date(2026, 3, 10),
            user_context=_user(),
        )

    assert result is None
    mocks.db.session.rollback.assert_called_once()
    mocks.log_processed_date.assert_not_called()
    assert [e["message"] for e in _logged_events(mocks.logger)] == [
        "Prescrição já foi processada (fluxo ambulatorial)"
    ]


def test_by_date_processes_a_pending_outpatient_admission():
    """A day with unprocessed items proceeds normally under the same flag."""
    with _by_date_env(
        _prescription(id=888),
        rows=_by_date_rows(),
        has_feature=True,
        outpatient_processed_status="PENDING",
    ) as mocks:
        _create_by_date(
            schema=SCHEMA,
            admission_number=ADMISSION,
            p_date=date(2026, 3, 10),
            user_context=_user(),
        )

    mocks.db.session.rollback.assert_not_called()
    mocks.log_processed_date.assert_called_once()


def test_by_date_marks_the_internal_prescriptions_as_processed():
    """Every individual prescription rolled into the day is stamped."""
    with _by_date_env(
        _prescription(id=888),
        rows=_by_date_rows(),
        internal_prescription_ids=[100100, 100200],
    ) as mocks:
        _create_by_date(
            schema=SCHEMA,
            admission_number=ADMISSION,
            p_date=date(2026, 3, 10),
            user_context=_user(),
        )

    mocks.log_processed_date.assert_called_once_with(
        id_prescription_array=[100100, 100200], schema=SCHEMA
    )


def test_by_date_runs_the_automatic_check_and_conciliation_update():
    """The CPOE flow finishes with the auto-check and conciliation hooks."""
    reloaded = _prescription(id=999)

    with prescalc_env(rows=_by_date_rows(reloaded=reloaded)) as mocks:
        with patch.object(
            prescription_agg_service.prescription_repository,
            "get_last_prescription",
            return_value=_prescription(id=888),
        ), patch.object(prescription_agg_service, "_automatic_check") as auto_check:
            _create_by_date(
                schema=SCHEMA,
                admission_number=ADMISSION,
                p_date=date(2026, 3, 10),
                user_context=_user(),
            )

    assert auto_check.call_args.kwargs["prescription"] is reloaded
    mocks.update_conciliation.assert_called_once_with(
        admission_number=ADMISSION, is_concilia=False
    )


# --------------------------------------------------------------------------
# _get_score_variation — the day-over-day delta shown in the queue
# --------------------------------------------------------------------------


def _run_score_variation(features, previous):
    """Invoke ``_get_score_variation`` with the previous-day row mocked."""
    prescription = _prescription(id=999, p_date=datetime(2026, 3, 10, 0, 0))
    fake_db = _fake_db([previous])

    with patch.object(prescription_agg_service, "db", fake_db):
        return prescription_agg_service._get_score_variation(
            prescription=prescription, features=features
        )


def test_score_variation_without_a_previous_day_is_a_full_increase():
    """The first day of an admission has nothing to compare against."""
    result = _run_score_variation(_features(globalScore=40), previous=None)

    assert result == {
        "variation": 100,
        "currentGlobalScore": 40,
        "previousGlobalScore": 0,
    }


def test_score_variation_treats_a_zero_previous_score_as_a_full_increase():
    """Dividing by the previous score is only meaningful when it is non-zero."""
    previous = _prescription(id=1, features={"globalScore": 0})

    result = _run_score_variation(_features(globalScore=40), previous=previous)

    assert result["variation"] == 100
    assert result["previousGlobalScore"] == 0


def test_score_variation_computes_a_percentage_increase():
    """A rise from 40 to 60 is reported as +50%."""
    previous = _prescription(id=1, features={"globalScore": 40})

    result = _run_score_variation(_features(globalScore=60), previous=previous)

    assert result == {
        "variation": 50.0,
        "currentGlobalScore": 60,
        "previousGlobalScore": 40,
    }


def test_score_variation_computes_a_percentage_decrease():
    """An improving patient yields a negative variation."""
    previous = _prescription(id=1, features={"globalScore": 80})

    result = _run_score_variation(_features(globalScore=60), previous=previous)

    assert result["variation"] == -25.0
    assert result["previousGlobalScore"] == 80


def test_score_variation_is_rounded_to_two_decimals():
    """The value is displayed as-is, so it is rounded at the source."""
    previous = _prescription(id=1, features={"globalScore": 30})

    result = _run_score_variation(_features(globalScore=40), previous=previous)

    assert result["variation"] == 33.33


def test_score_variation_defaults_a_missing_global_score_to_zero():
    """Features computed before scoring ran must not break the queue."""
    previous = _prescription(id=1, features={"globalScore": 40})

    result = _run_score_variation({}, previous=previous)

    assert result["currentGlobalScore"] == 0
    assert result["variation"] == -100.0


def test_score_variation_compares_against_the_previous_calendar_day():
    """The lookup id is the agg id of the same admission/segment, one day back."""
    prescription = _prescription(id=999, p_date=datetime(2026, 3, 10, 0, 0))
    fake_db = _fake_db([None])

    with patch.object(prescription_agg_service, "db", fake_db), patch.object(
        prescription_agg_service.prescriptionutils, "gen_agg_id"
    ) as gen_agg_id:
        prescription_agg_service._get_score_variation(
            prescription=prescription, features=_features()
        )

    assert gen_agg_id.call_args.kwargs == {
        "admission_number": ADMISSION,
        "id_segment": prescription.idSegment,
        "pdate": datetime(2026, 3, 9, 0, 0),
    }


# --------------------------------------------------------------------------
# _update_patient_conciliation_status
# --------------------------------------------------------------------------


def _run_conciliation_status(rows, *, is_concilia):
    """Invoke ``_update_patient_conciliation_status`` over ``rows``."""
    fake_db = _fake_db(rows)

    with patch.object(prescription_agg_service, "db", fake_db):
        prescription_agg_service._update_patient_conciliation_status(
            admission_number=ADMISSION, is_concilia=is_concilia
        )

    return fake_db


def _patient(status=PatientConciliationStatusEnum.PENDING.value):
    """Build a Patient row with a given conciliation status."""
    patient = Patient()
    patient.idPatient = 55
    patient.admissionNumber = ADMISSION
    patient.st_conciliation = status
    return patient


def test_a_conciliation_prescription_advances_the_patient_status():
    """The prescription being a conciliation is enough — no extra lookup."""
    patient = _patient()

    fake_db = _run_conciliation_status([patient], is_concilia=True)

    assert patient.st_conciliation == PatientConciliationStatusEnum.CREATED.value
    fake_db.session.flush.assert_called_once()


def test_an_existing_conciliation_elsewhere_advances_the_patient_status():
    """A regular prescription still advances a patient who has a conciliation."""
    patient = _patient()

    _run_conciliation_status([patient, SimpleNamespace(id=1)], is_concilia=False)

    assert patient.st_conciliation == PatientConciliationStatusEnum.CREATED.value


def test_a_patient_with_no_conciliation_at_all_stays_pending():
    """Nothing to record, so the status is left alone."""
    patient = _patient()

    fake_db = _run_conciliation_status([patient, None], is_concilia=False)

    assert patient.st_conciliation == PatientConciliationStatusEnum.PENDING.value
    fake_db.session.flush.assert_not_called()


def test_an_already_created_status_is_not_rewritten():
    """The transition is one-way: CREATED is never recomputed."""
    patient = _patient(status=PatientConciliationStatusEnum.CREATED.value)

    fake_db = _run_conciliation_status([patient], is_concilia=True)

    assert patient.st_conciliation == PatientConciliationStatusEnum.CREATED.value
    fake_db.session.flush.assert_not_called()


def test_a_missing_patient_is_tolerated():
    """Prescriptions can arrive before the admission row; that is not an error."""
    fake_db = _run_conciliation_status([None], is_concilia=True)

    fake_db.session.flush.assert_not_called()


# --------------------------------------------------------------------------
# _audit_create
# --------------------------------------------------------------------------


def test_audit_create_maps_the_prescription_header():
    """The audit row carries enough context to reconstruct the insert."""
    prescription = _prescription(id=999, p_date=datetime(2026, 3, 10, 8, 0))
    prescription.agg = True
    prescription.concilia = None
    fake_db = _fake_db()

    with patch.object(prescription_agg_service, "db", fake_db):
        prescription_agg_service._audit_create(prescription=prescription)

    audit = fake_db.session.added[0]
    assert audit.auditType == PrescriptionAuditTypeEnum.CREATE_AGG.value
    assert audit.idPrescription == 999
    assert audit.admissionNumber == ADMISSION
    assert audit.prescriptionDate == prescription.date
    assert audit.idDepartment == prescription.idDepartment
    assert audit.idSegment == prescription.idSegment
    assert audit.agg is True
    assert audit.bed == prescription.bed
    assert audit.extra is None
    # -1 marks "not counted": the items are only known after the roll-up
    assert audit.totalItens == -1
    # attributed to the prescalc service user, not to a person
    assert audit.createdBy == 0


# --------------------------------------------------------------------------
# _automatic_check
# --------------------------------------------------------------------------


def _run_automatic_check(features, *, status, has_feature):
    """Invoke ``_automatic_check`` and return the check-service mock."""
    prescription = _prescription(id=999, status=status)
    module = prescription_agg_service

    with patch.object(
        module.feature_service, "has_feature", return_value=has_feature
    ), patch.object(
        module.prescription_check_service, "check_prescription"
    ) as check_prescription:
        module._automatic_check(
            prescription=prescription, features=features, user_context=_user()
        )

    return check_prescription, prescription


def test_a_day_with_no_validated_items_is_checked_automatically():
    """Nothing for a pharmacist to review, so the day is closed by the system."""
    check_prescription, prescription = _run_automatic_check(
        _features(totalItens=0), status=0, has_feature=True
    )

    check_prescription.assert_called_once()
    kwargs = check_prescription.call_args.kwargs
    assert kwargs["idPrescription"] == prescription.id
    assert kwargs["p_status"] == "s"
    assert kwargs["alerts"] == []
    assert kwargs["fast_check"] is True
    assert kwargs["service_user"] is False


def test_a_day_with_items_is_left_for_a_pharmacist():
    """Anything reviewable must reach the work queue unchecked."""
    check_prescription, _ = _run_automatic_check(
        _features(totalItens=2), status=0, has_feature=True
    )

    check_prescription.assert_not_called()


def test_an_already_checked_day_is_not_checked_again():
    """Re-checking would create a spurious audit event."""
    check_prescription, _ = _run_automatic_check(
        _features(totalItens=0), status="s", has_feature=True
    )

    check_prescription.assert_not_called()


def test_the_automatic_check_is_behind_a_feature_flag():
    """Tenants without the flag keep every day in the queue."""
    check_prescription, _ = _run_automatic_check(
        _features(totalItens=0), status=0, has_feature=False
    )

    check_prescription.assert_not_called()


# --------------------------------------------------------------------------
# _log_processed_date and _set_schema
# --------------------------------------------------------------------------


def test_log_processed_date_stamps_the_items_of_every_prescription():
    """One PROCESSED audit row per item, attributed to the service user."""
    fake_db = _fake_db()

    with patch.object(prescription_agg_service, "db", fake_db):
        prescription_agg_service._log_processed_date(
            id_prescription_array=[100100, 100200], schema=SCHEMA
        )

    query, params = fake_db.session.execute.call_args.args
    assert f"insert into {SCHEMA}.presmed_audit" in str(query)
    assert params["auditType"] == PrescriptionDrugAuditTypeEnum.PROCESSED.value
    assert params["prescriptionArray"] == [100100, 100200]


def test_set_schema_rejects_an_unknown_schema():
    """A bad schema name must fail loudly instead of querying the wrong tenant."""
    module = prescription_agg_service
    session = MagicMock()
    session.execute.return_value = [("public",), ("demo",)]

    with patch.object(module, "db"), patch.object(
        module, "Session", return_value=session
    ), patch.object(module, "dbSession") as db_session:
        with pytest.raises(ValidationError) as exc:
            module._set_schema("does_not_exist")

    assert exc.value.code == "errors.invalidSchema"
    assert exc.value.httpStatus == 400
    db_session.setSchema.assert_not_called()


def test_set_schema_switches_to_a_known_schema():
    """A valid schema is handed to the session's tenant switch."""
    module = prescription_agg_service
    session = MagicMock()
    session.execute.return_value = [("public",), ("demo",)]

    with patch.object(module, "db"), patch.object(
        module, "Session", return_value=session
    ), patch.object(module, "dbSession") as db_session:
        module._set_schema("demo")

    db_session.setSchema.assert_called_once_with("demo")
    # the probe session is not left open
    session.close.assert_called_once()
