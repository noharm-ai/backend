"""Integration tests for ``GET /reports/prescription/history``.

The prescription-history report is the timeline a pharmacist opens to answer
"what happened to this prescription, when, and who did it". Nothing in the
suite touched it — neither
``services/reports/reports_prescription_history_service.py`` nor the two
queries behind it in
``repository/reports/reports_prescription_history_repository.py``.

The timeline is assembled from two very different sources, and every rule that
decides what ends up in it is exercised here:

* three synthetic ``custom`` events that exist only in this report — origin
  creation (type 1, taken from ``prescricao.dtcriacao_origem``), arrival
  (type 2) and processing (type 3), both derived from the earliest matching
  ``presmed_audit`` row. All three are suppressed for aggregated
  prescriptions, where the report shows the audit trail alone;
* the arrival event only looks at items the report counts as prescribed
  content, so a ``Materiais`` line that reached the backend first must not
  move the arrival date;
* every ``prescricao_audit`` row becomes an event whose ``responsible`` is
  resolved through an outer join — an audit written by an id with no
  ``usuario`` row still renders, with no responsible.

The merged list is returned sorted by ``createdAt``, interleaving both
sources.

Prescriptions come from ``test_counters`` (ids >= 100000) and their items from
the ``>= 100000001`` range, so the session-scoped ``clean_test_artifacts``
fixture removes them — including the audit rows, which are deleted by
prescription/item id.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from models.enums import (
    DrugTypeEnum,
    PrescriptionAuditTypeEnum,
    PrescriptionDrugAuditTypeEnum,
)
from models.prescription import PrescriptionAudit, PrescriptionDrugAudit
from tests.conftest import session, session_commit
from tests.utils.utils_test_prescription import (
    create_prescription,
    create_prescription_drug,
    test_counters,
)
from utils import status

URL = "/reports/prescription/history"

# the user behind every fixture in tests.conftest.get_access
CALLER_ID = 1
CALLER_NAME = "Demonstração"

# an id with no demo.usuario row, to drive the outer join's null side
UNKNOWN_USER_ID = 987654

UNKNOWN_PRESCRIPTION = 999999999

# event types the service assigns to the synthetic entries
ORIGIN_EVENT = 1
ARRIVAL_EVENT = 2
PROCESS_EVENT = 3

# a fixed base date keeps the expected ordering readable
BASE_DATE = datetime(2024, 3, 11, 8, 0, 0)


def _next_prescription_ids():
    """Reserve a prescription id + admission number no other test uses."""
    id_prescription = test_counters["id_prescription"]
    admission_number = test_counters["admission_number"]
    test_counters["id_prescription"] += 1
    test_counters["admission_number"] += 1

    return id_prescription, admission_number


def _create_prescription(agg: bool = None, origin_created_at: datetime = None):
    """Create a prescription in the reserved id range, optionally aggregated."""
    id_prescription, admission_number = _next_prescription_ids()

    prescription = create_prescription(
        id=id_prescription,
        admissionNumber=admission_number,
        idPatient=id_prescription,
        date=BASE_DATE,
        expire=BASE_DATE + timedelta(days=1),
        agg=agg,
    )

    if origin_created_at is not None:
        prescription.origin_created_at = origin_created_at
        session_commit()

    return prescription


def _create_item(prescription, order: int, source: str = DrugTypeEnum.DRUG.value):
    """Add one item to ``prescription``; ids stay in the >= 100000001 range.

    ``presmed`` carries a BEFORE INSERT trigger that normalises ``origem``
    through the ``map-origin-*`` entries in ``memoria``, and the seed has no
    mapping for ``Materiais`` — anything unmapped lands as ``Medicamentos``.
    The source is therefore written back afterwards (the trigger does not fire
    on UPDATE), which is what the report reads.
    """
    id_item = int(f"{prescription.id}{order:03d}")

    create_prescription_drug(
        id=id_item,
        idPrescription=prescription.id,
        idDrug=3,
        source=source,
    )

    session.execute(
        text("UPDATE demo.presmed SET origem = :source WHERE fkpresmed = :id"),
        {"source": source, "id": id_item},
    )
    session_commit()

    return id_item


def _audit_item(id_item: int, audit_type: PrescriptionDrugAuditTypeEnum, created_at):
    """Write a presmed_audit row for one prescription item."""
    audit = PrescriptionDrugAudit()
    audit.auditType = audit_type.value
    audit.idPrescriptionDrug = id_item
    audit.createdAt = created_at
    audit.createdBy = CALLER_ID

    session.add(audit)
    session_commit()

    return audit


def _audit_prescription(
    prescription,
    audit_type: PrescriptionAuditTypeEnum,
    created_at,
    created_by: int = CALLER_ID,
    extra=None,
):
    """Write a prescricao_audit row for the whole prescription."""
    audit = PrescriptionAudit()
    audit.auditType = audit_type.value
    audit.admissionNumber = prescription.admissionNumber
    audit.idPrescription = prescription.id
    audit.prescriptionDate = prescription.date
    audit.idDepartment = prescription.idDepartment
    audit.idSegment = prescription.idSegment
    audit.totalItens = 1
    audit.agg = prescription.agg
    audit.bed = prescription.bed
    audit.extra = extra
    audit.createdAt = created_at
    audit.createdBy = created_by

    session.add(audit)
    session_commit()

    return audit


def _get_history(client, headers, id_prescription):
    """Call the endpoint and return the raw response."""
    return client.get(f"{URL}?idPrescription={id_prescription}", headers=headers)


def _custom_events(data):
    """The synthetic entries, keyed by their event type."""
    return {e["type"]: e for e in data if e["source"] == "custom"}


def test_timeline_merges_custom_events_with_the_audit_trail(client, analyst_headers):
    """The timeline mixes the three synthetic events with prescricao_audit rows [200]."""
    origin_date = BASE_DATE
    arrival_date = BASE_DATE + timedelta(minutes=5)
    process_date = BASE_DATE + timedelta(minutes=10)
    check_date = BASE_DATE + timedelta(minutes=20)

    prescription = _create_prescription(origin_created_at=origin_date)
    id_item = _create_item(prescription, 1)

    _audit_item(id_item, PrescriptionDrugAuditTypeEnum.UPSERT, arrival_date)
    _audit_item(id_item, PrescriptionDrugAuditTypeEnum.PROCESSED, process_date)
    _audit_prescription(prescription, PrescriptionAuditTypeEnum.CHECK, check_date)

    response = _get_history(client, analyst_headers, prescription.id)
    assert response.status_code == status.HTTP_200_OK

    data = response.get_json()["data"]

    assert [e["source"] for e in data] == [
        "custom",
        "custom",
        "custom",
        "PrescriptionAudit",
    ]
    assert [e["type"] for e in data] == [
        ORIGIN_EVENT,
        ARRIVAL_EVENT,
        PROCESS_EVENT,
        PrescriptionAuditTypeEnum.CHECK.value,
    ]
    assert [e["createdAt"] for e in data] == [
        origin_date.isoformat(),
        arrival_date.isoformat(),
        process_date.isoformat(),
        check_date.isoformat(),
    ]

    # every entry reports the prescription it belongs to, as a string
    assert {e["idPrescription"] for e in data} == {str(prescription.id)}

    events = _custom_events(data)
    assert events[ORIGIN_EVENT]["responsible"] == "Sistema origem"
    # arrival and processing are machine events with no author
    assert events[ARRIVAL_EVENT]["responsible"] is None
    assert events[PROCESS_EVENT]["responsible"] is None
    assert data[3]["responsible"] == CALLER_NAME


def test_events_are_returned_sorted_by_date(client, analyst_headers):
    """Audit rows written out of order are still returned oldest first [200]."""
    prescription = _create_prescription()

    late = BASE_DATE + timedelta(hours=3)
    early = BASE_DATE + timedelta(hours=1)
    middle = BASE_DATE + timedelta(hours=2)

    _audit_prescription(prescription, PrescriptionAuditTypeEnum.CHECK, late)
    _audit_prescription(prescription, PrescriptionAuditTypeEnum.UNCHECK, early)
    _audit_prescription(prescription, PrescriptionAuditTypeEnum.REVISION, middle)

    data = _get_history(client, analyst_headers, prescription.id).get_json()["data"]

    assert [e["createdAt"] for e in data] == [
        early.isoformat(),
        middle.isoformat(),
        late.isoformat(),
    ]


def test_arrival_date_ignores_material_items(client, analyst_headers):
    """A Materiais line audited first must not become the arrival date [200]."""
    material_date = BASE_DATE + timedelta(minutes=1)
    drug_date = BASE_DATE + timedelta(minutes=30)

    prescription = _create_prescription()
    id_material = _create_item(prescription, 1, source=DrugTypeEnum.MATERIAL.value)
    id_drug = _create_item(prescription, 2, source=DrugTypeEnum.DRUG.value)

    _audit_item(id_material, PrescriptionDrugAuditTypeEnum.UPSERT, material_date)
    _audit_item(id_drug, PrescriptionDrugAuditTypeEnum.UPSERT, drug_date)

    data = _get_history(client, analyst_headers, prescription.id).get_json()["data"]

    events = _custom_events(data)
    assert events[ARRIVAL_EVENT]["createdAt"] == drug_date.isoformat()


def test_arrival_date_is_the_earliest_upsert(client, analyst_headers):
    """With several items the arrival date is the first one the backend saw [200]."""
    first = BASE_DATE + timedelta(minutes=2)
    second = BASE_DATE + timedelta(minutes=40)

    prescription = _create_prescription()
    id_solution = _create_item(prescription, 1, source=DrugTypeEnum.SOLUTION.value)
    id_diet = _create_item(prescription, 2, source=DrugTypeEnum.DIET.value)

    _audit_item(id_diet, PrescriptionDrugAuditTypeEnum.UPSERT, second)
    _audit_item(id_solution, PrescriptionDrugAuditTypeEnum.UPSERT, first)

    data = _get_history(client, analyst_headers, prescription.id).get_json()["data"]

    events = _custom_events(data)
    assert events[ARRIVAL_EVENT]["createdAt"] == first.isoformat()


def test_prescription_without_origin_date_has_no_origin_event(client, analyst_headers):
    """dtcriacao_origem is optional; without it the origin event is skipped [200]."""
    prescription = _create_prescription()
    id_item = _create_item(prescription, 1)
    _audit_item(
        id_item,
        PrescriptionDrugAuditTypeEnum.UPSERT,
        BASE_DATE + timedelta(minutes=5),
    )

    data = _get_history(client, analyst_headers, prescription.id).get_json()["data"]

    events = _custom_events(data)
    assert ORIGIN_EVENT not in events
    assert ARRIVAL_EVENT in events


def test_items_never_processed_have_no_process_event(client, analyst_headers):
    """Only a PROCESSED audit row produces the processing event [200]."""
    prescription = _create_prescription()
    id_item = _create_item(prescription, 1)
    _audit_item(
        id_item,
        PrescriptionDrugAuditTypeEnum.UPSERT,
        BASE_DATE + timedelta(minutes=5),
    )

    data = _get_history(client, analyst_headers, prescription.id).get_json()["data"]

    assert PROCESS_EVENT not in _custom_events(data)


def test_aggregated_prescription_hides_the_custom_events(client, analyst_headers):
    """An aggregated prescription shows the audit trail only [200]."""
    prescription = _create_prescription(
        agg=True, origin_created_at=BASE_DATE - timedelta(hours=1)
    )
    id_item = _create_item(prescription, 1)

    _audit_item(
        id_item, PrescriptionDrugAuditTypeEnum.UPSERT, BASE_DATE + timedelta(minutes=5)
    )
    _audit_item(
        id_item,
        PrescriptionDrugAuditTypeEnum.PROCESSED,
        BASE_DATE + timedelta(minutes=6),
    )
    _audit_prescription(
        prescription,
        PrescriptionAuditTypeEnum.CREATE_AGG,
        BASE_DATE + timedelta(minutes=7),
    )

    data = _get_history(client, analyst_headers, prescription.id).get_json()["data"]

    assert _custom_events(data) == {}
    assert [e["type"] for e in data] == [PrescriptionAuditTypeEnum.CREATE_AGG.value]


def test_audit_written_by_an_unknown_user_has_no_responsible(client, analyst_headers):
    """The user join is optional, so an orphan audit row still renders [200]."""
    prescription = _create_prescription()
    _audit_prescription(
        prescription,
        PrescriptionAuditTypeEnum.CHECK,
        BASE_DATE + timedelta(minutes=5),
        created_by=UNKNOWN_USER_ID,
    )

    data = _get_history(client, analyst_headers, prescription.id).get_json()["data"]

    assert len(data) == 1
    assert data[0]["responsible"] is None


def test_audit_extra_payload_is_returned(client, analyst_headers):
    """The audit's extra column is handed to the client untouched [200]."""
    extra = {"idProtocol": 7, "reason": "teste"}

    prescription = _create_prescription()
    _audit_prescription(
        prescription,
        PrescriptionAuditTypeEnum.REVISION,
        BASE_DATE + timedelta(minutes=5),
        extra=extra,
    )

    data = _get_history(client, analyst_headers, prescription.id).get_json()["data"]

    assert data[0]["extra"] == extra


def test_prescription_without_history_returns_an_empty_timeline(
    client, analyst_headers
):
    """A prescription nobody touched has nothing to show, but is not an error [200]."""
    prescription = _create_prescription()

    response = _get_history(client, analyst_headers, prescription.id)

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"] == []


@pytest.mark.parametrize(
    "query",
    ["", f"?idPrescription={UNKNOWN_PRESCRIPTION}"],
    ids=["missing id", "unknown id"],
)
def test_history_requires_an_existing_prescription(client, analyst_headers, query):
    """Without a prescription to report on, the request is refused [400]."""
    response = client.get(f"{URL}{query}", headers=analyst_headers)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.invalidRecord"


def test_role_without_read_reports_is_refused(client, user_manager_headers):
    """USER_MANAGER holds no READ_REPORTS, so the timeline is out of reach [401]."""
    prescription = _create_prescription()

    response = _get_history(client, user_manager_headers, prescription.id)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
