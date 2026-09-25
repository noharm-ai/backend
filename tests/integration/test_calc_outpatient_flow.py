"""Tests: outpatient patient-day flow (``PATIENT_DAY_OUTPATIENT_FLOW``)

In the regular CPOE flow every ``atendcalc`` run rebuilds the patient-day
prescription. Outpatient units run ``atendcalc`` far more often than items
actually change, so when the ``PATIENT_DAY_OUTPATIENT_FLOW`` feature is enabled
the run is skipped whenever nothing new arrived for the day being aggregated.

The decision comes from ``prescalc_repository.get_processed_outpatient_status``,
which reads the ``presmed_audit`` trail:

* an item carrying an ``UPSERT`` audit *on the aggregation date* is "new" — the
  row is written by the ``complete_presmed`` database trigger whenever an item
  is loaded, so creating an item here produces it for free;
* a new item is settled once it also carries a ``PROCESSED`` audit, of any date,
  since the item may have been processed by a later run;
* any unsettled new item makes the whole day ``PENDING``; otherwise the day is
  ``PROCESSED`` and ``create_agg_prescription_by_date`` rolls back and returns.

Items that did not change on the aggregation date are outside the join
entirely, which is why a day with no arrivals reports ``PROCESSED``.

Every date here is taken from the audit rows the database itself wrote, so the
assertions do not depend on the timezone the test process runs in.
"""

import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from models.enums import FeatureEnum, PrescriptionDrugAuditTypeEnum
from models.main import db
from models.prescription import Prescription, PrescriptionDrug, PrescriptionDrugAudit
from repository import prescalc_repository
from static import atendcalc
from tests.conftest import session, session_commit
from tests.utils import utils_test_prescription
from utils.static_context import static_user_context

OUTPATIENT_FLOW = FeatureEnum.PATIENT_DAY_OUTPATIENT_FLOW.value

# the audit trail is stamped by the integration layer, which has no user id
LOADER_ID = 0


def _read_features():
    """Return the feature list currently stored in the demo schema."""
    row = session.execute(
        text("SELECT valor FROM demo.memoria WHERE tipo = 'features'")
    ).first()
    return list(row[0]) if row else []


def _write_features(features):
    """Overwrite the demo schema feature list."""
    session.execute(
        text(
            "UPDATE demo.memoria SET valor = CAST(:value AS json) WHERE tipo = 'features'"
        ),
        {"value": json.dumps(features)},
    )
    session_commit()


@pytest.fixture
def outpatient_flow():
    """Enable PATIENT_DAY_OUTPATIENT_FLOW for the demo schema."""
    original = _read_features()
    _write_features(original + [OUTPATIENT_FLOW])
    yield
    _write_features(original)


@pytest.fixture
def no_outpatient_flow():
    """Make sure PATIENT_DAY_OUTPATIENT_FLOW is *not* enabled for the demo schema."""
    original = _read_features()
    _write_features([f for f in original if f != OUTPATIENT_FLOW])
    yield
    _write_features(original)


def _item_ids(id_prescription: int):
    """The presmed ids of a prescription, in insertion order."""
    return [
        row.id
        for row in session.query(PrescriptionDrug)
        .filter(PrescriptionDrug.idPrescription == id_prescription)
        .order_by(PrescriptionDrug.id)
        .all()
    ]


def _audits(id_prescription: int, audit_type: PrescriptionDrugAuditTypeEnum):
    """The audit rows of one kind written for the items of a prescription."""
    return (
        session.query(PrescriptionDrugAudit)
        .filter(
            PrescriptionDrugAudit.auditType == audit_type.value,
            PrescriptionDrugAudit.idPrescriptionDrug.in_(_item_ids(id_prescription)),
        )
        .all()
    )


def _arrival_date(id_prescription: int):
    """The date the database stamped on the items' UPSERT audit rows."""
    upserts = _audits(id_prescription, PrescriptionDrugAuditTypeEnum.UPSERT)
    assert upserts, "the complete_presmed trigger should have written an UPSERT audit"

    return upserts[0].createdAt


def _shift_arrival(id_prescription: int, days: int):
    """Move the items' UPSERT audit rows to another day."""
    session.execute(
        text(
            "UPDATE demo.presmed_audit SET created_at = created_at - CAST(:days AS interval) "
            "WHERE tp_audit = :kind AND fkpresmed = ANY(:items)"
        ),
        {
            "days": f"{days} days",
            "kind": PrescriptionDrugAuditTypeEnum.UPSERT.value,
            "items": _item_ids(id_prescription),
        },
    )
    session_commit()


def _align_arrivals(id_prescription: int):
    """Stamp the items' UPSERT audits with the date ``atendcalc`` aggregates.

    The ``complete_presmed`` trigger writes ``now()`` in America/Sao_Paulo while
    ``atendcalc`` aggregates ``datetime.today().date()`` as the process reads it.
    On a UTC runner the two disagree for the first three hours of the day, which
    has nothing to do with the behaviour under test — so the arrivals are pinned
    to the aggregation date here.
    """
    session.execute(
        text(
            "UPDATE demo.presmed_audit SET created_at = :created_at "
            "WHERE tp_audit = :kind AND fkpresmed = ANY(:items)"
        ),
        {
            "created_at": datetime.today(),
            "kind": PrescriptionDrugAuditTypeEnum.UPSERT.value,
            "items": _item_ids(id_prescription),
        },
    )
    session_commit()


def _mark_processed(id_item: int, created_at):
    """Write the PROCESSED audit row the aggregation would have written."""
    audit = PrescriptionDrugAudit()
    audit.auditType = PrescriptionDrugAuditTypeEnum.PROCESSED.value
    audit.idPrescriptionDrug = id_item
    audit.createdAt = created_at
    audit.createdBy = LOADER_ID

    session.add(audit)
    session_commit()

    return audit


def _outpatient_status(id_prescription_list, agg_date):
    """Call the repository the way the agg service does: static context + demo schema."""
    with static_user_context("demo"):
        db.session.connection(execution_options={"schema_translate_map": {None: "demo"}})
        try:
            return prescalc_repository.get_processed_outpatient_status(
                id_prescription_list=id_prescription_list, agg_date=agg_date
            )
        finally:
            db.session.rollback()
            db.session.remove()


def _processed_count(id_prescription: int):
    """How many PROCESSED audit rows the items of a prescription carry."""
    return len(_audits(id_prescription, PrescriptionDrugAuditTypeEnum.PROCESSED))


def _patient_day(admission_number: int):
    """The aggregated (patient-day) prescription of an admission, if any."""
    session.expire_all()
    return (
        session.query(Prescription)
        .filter(Prescription.agg)
        .filter(Prescription.admissionNumber == admission_number)
        .first()
    )


# ─── get_processed_outpatient_status ──────────────────────────────────────────


def test_newly_loaded_items_leave_the_day_pending():
    """Items loaded today carry an UPSERT audit and no PROCESSED one yet."""
    prescription = utils_test_prescription.create_basic_prescription(cpoe=True)
    arrival = _arrival_date(prescription.id)

    assert _outpatient_status([prescription.id], arrival) == "PENDING"


def test_day_is_processed_once_every_arrival_is_settled():
    """A PROCESSED audit on each item of the day settles it."""
    prescription = utils_test_prescription.create_basic_prescription(cpoe=True)
    arrival = _arrival_date(prescription.id)

    for id_item in _item_ids(prescription.id):
        _mark_processed(id_item, arrival)

    assert _outpatient_status([prescription.id], arrival) == "PROCESSED"


def test_a_single_unsettled_item_makes_the_whole_day_pending():
    """One settled item does not cover an unsettled sibling."""
    prescription = utils_test_prescription.create_basic_prescription(cpoe=True)
    arrival = _arrival_date(prescription.id)
    settled, _unsettled = _item_ids(prescription.id)

    _mark_processed(settled, arrival)

    assert _outpatient_status([prescription.id], arrival) == "PENDING"


def test_day_without_any_arrival_is_processed():
    """No UPSERT audit on the aggregation date: nothing to do, so the day is PROCESSED."""
    prescription = utils_test_prescription.create_basic_prescription(cpoe=True)
    arrival = _arrival_date(prescription.id)

    # the items arrived the day before the one being aggregated, and were never
    # processed — they still must not hold today's aggregation back
    _shift_arrival(prescription.id, days=1)

    assert _outpatient_status([prescription.id], arrival) == "PROCESSED"


def test_arrival_of_a_later_day_does_not_count_either():
    """The UPSERT audit has to fall on the aggregation date, not merely before it."""
    prescription = utils_test_prescription.create_basic_prescription(cpoe=True)
    arrival = _arrival_date(prescription.id)

    assert _outpatient_status([prescription.id], arrival - timedelta(days=1)) == (
        "PROCESSED"
    )


def test_processed_audit_of_an_earlier_day_still_settles_the_item():
    """The PROCESSED join is not date-bound: an item settled by an earlier run stays settled."""
    prescription = utils_test_prescription.create_basic_prescription(cpoe=True)
    arrival = _arrival_date(prescription.id)

    for id_item in _item_ids(prescription.id):
        _mark_processed(id_item, arrival - timedelta(days=2))

    assert _outpatient_status([prescription.id], arrival) == "PROCESSED"


def test_only_the_listed_prescriptions_are_considered():
    """An unsettled arrival outside the aggregated set does not make the day pending."""
    watched = utils_test_prescription.create_basic_prescription(cpoe=True)
    other = utils_test_prescription.create_basic_prescription(cpoe=True)
    arrival = _arrival_date(watched.id)

    for id_item in _item_ids(watched.id):
        _mark_processed(id_item, arrival)

    assert _outpatient_status([watched.id], arrival) == "PROCESSED"
    assert _outpatient_status([watched.id, other.id], arrival) == "PENDING"


def test_empty_prescription_list_is_processed():
    """No prescription to look at means there is nothing pending."""
    prescription = utils_test_prescription.create_basic_prescription(cpoe=True)

    assert _outpatient_status([], _arrival_date(prescription.id)) == "PROCESSED"


# ─── create_agg_prescription_by_date (atendcalc) ──────────────────────────────


def test_atendcalc_skips_a_day_already_processed(outpatient_flow):
    """With the feature on, a second run over an unchanged day does not reprocess it."""
    prescription = utils_test_prescription.create_basic_prescription(cpoe=True)
    _align_arrivals(prescription.id)

    response = json.loads(
        atendcalc(
            {"schema": "demo", "admission_number": prescription.admissionNumber}, None
        )
    )
    assert response.get("status") == "success"
    assert _patient_day(prescription.admissionNumber) is not None

    # the first run settled every item it aggregated
    after_first_run = _processed_count(prescription.id)
    assert after_first_run > 0

    # nothing arrived since, so the second run must bail out before reprocessing
    response = json.loads(
        atendcalc(
            {"schema": "demo", "admission_number": prescription.admissionNumber}, None
        )
    )
    assert response.get("status") == "success"
    assert _processed_count(prescription.id) == after_first_run


def test_atendcalc_reprocesses_when_a_new_item_arrives(outpatient_flow):
    """With the feature on, an unsettled arrival of the day brings the run back."""
    prescription = utils_test_prescription.create_basic_prescription(cpoe=True)
    _align_arrivals(prescription.id)

    atendcalc({"schema": "demo", "admission_number": prescription.admissionNumber}, None)
    after_first_run = _processed_count(prescription.id)
    assert after_first_run > 0

    # a new item is loaded today: the trigger stamps its UPSERT audit
    utils_test_prescription.create_prescription_drug(
        id=int(f"{prescription.id}003"), idPrescription=prescription.id, idDrug=5
    )
    _align_arrivals(prescription.id)

    response = json.loads(
        atendcalc(
            {"schema": "demo", "admission_number": prescription.admissionNumber}, None
        )
    )
    assert response.get("status") == "success"
    assert _processed_count(prescription.id) > after_first_run


def test_atendcalc_always_reprocesses_without_the_feature(no_outpatient_flow):
    """With the feature off, the same unchanged day is reprocessed on every run."""
    prescription = utils_test_prescription.create_basic_prescription(cpoe=True)

    atendcalc({"schema": "demo", "admission_number": prescription.admissionNumber}, None)
    after_first_run = _processed_count(prescription.id)
    assert after_first_run > 0

    atendcalc({"schema": "demo", "admission_number": prescription.admissionNumber}, None)

    assert _processed_count(prescription.id) > after_first_run
