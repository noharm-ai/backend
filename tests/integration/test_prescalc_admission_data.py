"""Tests: prescalc reads once what belongs to the admission

Prescalc (non-CPOE) builds the prescription view twice in a row: of the
prescription it received and of its prescription-day. Both belong to the same
admission, so what does not depend on the prescription (configs,
interventions, allergies, clinical notes stats, exams) is read by the first
view and reused by the second (static_get_prescription's admission_data).
Only what depends on the items is read by both.

Prescalc is the most executed flow of the application: these tests keep its
reads from growing back unnoticed, and check that sharing them changes
nothing in the view.
"""

import json

from sqlalchemy import event, inspect
from sqlalchemy.engine import Engine

from models.main import db, dbSession
from repository import (
    allergy_repository,
    clinical_notes_repository,
    prescription_view_repository,
)
from services import (
    alert_interaction_service,
    exams_service,
    intervention_service,
    memory_service,
    prescription_view_service,
    segment_service,
)
from static import prescalc
from tests.utils import utils_test_prescription
from utils import prescriptionutils
from utils.static_context import static_user_context

# seed prescription of an admission with a patient record (pessoa)
SEED_PRESCRIPTION = 20
# statements of a prescalc run (test_prescalc_statements_stay_within_budget)
STATEMENT_BUDGET = 38


def _spy(monkeypatch, module, name) -> list:
    """Counts the calls of module.name, which still runs"""
    calls = []
    original = getattr(module, name)

    def spy(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(module, name, spy)

    return calls


def _prescalc(id_prescription: int):
    """Runs prescalc, which must succeed"""
    response = json.loads(
        prescalc(
            {"schema": "demo", "id_prescription": id_prescription, "force": False},
            None,
        )
    )
    assert response["status"] == "success", response


def _statements(run) -> list[str]:
    """The SQL statements run() executes"""
    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(Engine, "before_cursor_execute", record)
    try:
        run()
    finally:
        event.remove(Engine, "before_cursor_execute", record)

    return statements


def _without_run_time(view):
    """The view without the time it was computed at (processedDate of each
    header's indicators), which no two views share"""
    if isinstance(view, dict):
        return {
            key: _without_run_time(value)
            for key, value in view.items()
            if key != "processedDate"
        }

    if isinstance(view, list):
        return [_without_run_time(value) for value in view]

    return view


def _agg_id(prescription) -> int:
    """Id of the prescription-day prescalc creates for the prescription"""
    return prescriptionutils.gen_agg_id(
        admission_number=prescription.admissionNumber,
        id_segment=prescription.idSegment,
        pdate=prescription.date,
    )


def test_prescalc_reads_admission_data_once(monkeypatch):
    """The two views of a prescalc run read the admission's data once, and
    the items of each one"""
    prescription = utils_test_prescription.create_basic_prescription()

    once = {
        "configs": _spy(monkeypatch, memory_service, "get_by_kind"),
        "segment": _spy(monkeypatch, segment_service, "is_cpoe"),
        "interventions": _spy(monkeypatch, intervention_service, "get_interventions"),
        "allergy records": _spy(monkeypatch, allergy_repository, "get_allergy_records"),
        "allergies by substance": _spy(
            monkeypatch, alert_interaction_service, "_get_allergies"
        ),
        "clinical notes stats": _spy(
            monkeypatch, clinical_notes_repository, "get_admission_stats"
        ),
        "exams": _spy(monkeypatch, exams_service, "find_latest_exams"),
    }
    drug_lists = _spy(
        monkeypatch, prescription_view_repository, "find_drugs_by_prescription"
    )

    _prescalc(prescription.id)

    assert {name: len(calls) for name, calls in once.items()} == {
        name: 1 for name in once
    }
    # the prescription's items and the prescription-day's
    assert len(drug_lists) == 2


def test_view_with_admission_data_is_the_same(monkeypatch):
    """A view that reuses the admission's data equals the one that reads it"""
    prescription = utils_test_prescription.create_basic_prescription()
    _prescalc(prescription.id)
    id_agg = _agg_id(prescription)

    with static_user_context("demo") as user_context:
        dbSession.setSchema("demo")

        alone = prescription_view_service.static_get_prescription(
            id_prescription=id_agg, user_context=user_context
        )

        admission_data = {}
        prescription_view_service.static_get_prescription(
            id_prescription=prescription.id,
            user_context=user_context,
            admission_data=admission_data,
        )
        interventions = _spy(monkeypatch, intervention_service, "get_interventions")
        shared = prescription_view_service.static_get_prescription(
            id_prescription=id_agg,
            user_context=user_context,
            admission_data=admission_data,
        )

        db.session.rollback()
        db.session.remove()

    assert not interventions
    assert shared["headers"]
    assert _without_run_time(shared) == _without_run_time(alone)


def test_admission_data_is_not_reused_for_another_admission():
    """What was read for an admission is dropped when the next view is of
    another one"""
    first = utils_test_prescription.create_basic_prescription()
    second = utils_test_prescription.create_basic_prescription()
    assert first.admissionNumber != second.admissionNumber

    with static_user_context("demo") as user_context:
        dbSession.setSchema("demo")

        alone = prescription_view_service.static_get_prescription(
            id_prescription=second.id, user_context=user_context
        )

        admission_data = {}
        prescription_view_service.static_get_prescription(
            id_prescription=first.id,
            user_context=user_context,
            admission_data=admission_data,
        )
        assert admission_data["scope"][0] == first.admissionNumber

        shared = prescription_view_service.static_get_prescription(
            id_prescription=second.id,
            user_context=user_context,
            admission_data=admission_data,
        )

        db.session.rollback()
        db.session.remove()

    assert admission_data["scope"][0] == second.admissionNumber
    assert _without_run_time(shared) == _without_run_time(alone)


def test_view_loads_its_deferred_columns_with_the_prescription():
    """The deferred columns the view always reads come in its first query, not
    in a query each"""
    with static_user_context("demo"):
        dbSession.setSchema("demo")

        prescription, patient, _, _, _, _ = (
            prescription_view_service._get_prescription_data(
                id_prescription=SEED_PRESCRIPTION
            )
        )
        unloaded_prescription = set(inspect(prescription).unloaded)
        unloaded_patient = set(inspect(patient).unloaded)

        db.session.rollback()
        db.session.remove()

    assert "notes" not in unloaded_prescription
    assert not {"observation", "alert"} & unloaded_patient


def test_prescalc_statements_stay_within_budget():
    """A prescalc run stays within its statement budget.

    Every statement is a round trip to the database on the most executed flow
    of the application. The budget has some room over what a run takes today
    (about 30 on this prescription): raise it only for a read prescalc really
    needs, and look first for one it already does."""
    prescription = utils_test_prescription.create_basic_prescription()
    _prescalc(prescription.id)

    # one more item, so the run recalculates the prescription and its day
    utils_test_prescription.create_prescription_drug(
        id=int(f"{prescription.id}003"), idPrescription=prescription.id, idDrug=5
    )

    statements = _statements(lambda: _prescalc(prescription.id))

    assert len(statements) <= STATEMENT_BUDGET, "\n".join(statements)
