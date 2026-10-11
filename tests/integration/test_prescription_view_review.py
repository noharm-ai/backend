"""Tests: the review block of GET /prescriptions/<idPrescription>

When a pharmacist reviews a patient (POST /prescriptions/review), the
prescription screen shows who did it and when. The view does not store that
anywhere: it reads it back from the REVISION rows of ``prescricao_audit``
(``prescription_view_service._get_review_data``). These tests pin down that
read:

* a reviewed aggregated prescription reports ``reviewed``, the reviewer's name
  and the time of the review, taken from the audit the review endpoint wrote;
* when a patient was reviewed more than once, the latest REVISION wins, and
  the UNDO_REVISION rows of the trail are not mistaken for a review;
* undoing the review clears the whole block;
* a prescription flagged as reviewed with no REVISION trail (e.g. written by
  the integration) still reports ``reviewed``, with no reviewer to show.

``test_prescription_view.py`` only covers the block of a prescription that was
never reviewed.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from models.enums import PrescriptionAuditTypeEnum, PrescriptionReviewTypeEnum
from models.prescription import PrescriptionAudit
from tests.conftest import session, session_commit
from tests.utils.utils_test_prescription import (
    create_prescription,
    create_prescription_drug,
    test_counters,
)

REVIEW_URL = "/prescriptions/review"

REVIEWED = PrescriptionReviewTypeEnum.REVIEWED.value
PENDING = PrescriptionReviewTypeEnum.PENDING.value

# seed users (public.usuario): the caller of every conftest fixture, and two
# other users to sign hand-written audits with
CALLER_NAME = "Demonstração"
ADMIN_USER_ID = 2
ADMIN_USER_NAME = "User Admin"
CURATOR_USER_ID = 3
CURATOR_USER_NAME = "User Curator"


def _view(client, headers, id_prescription: int) -> dict:
    """GET the prescription view and return its ``data`` payload."""
    response = client.get(f"/prescriptions/{id_prescription}", headers=headers)
    assert response.status_code == 200

    return response.get_json()["data"]


def _review(client, headers, id_prescription: int, review_type: int) -> None:
    """Toggle the review of an aggregated prescription through the API."""
    response = client.post(
        REVIEW_URL,
        json={"idPrescription": str(id_prescription), "reviewType": review_type},
        headers=headers,
    )
    assert response.status_code == 200


def _add_audit(
    id_prescription: int,
    admission_number: int,
    audit_type: int,
    created_by: int,
    created_at: datetime,
) -> None:
    """Write a ``prescricao_audit`` row by hand, signed by ``created_by``."""
    audit = PrescriptionAudit()
    audit.auditType = audit_type
    audit.admissionNumber = admission_number
    audit.idPrescription = id_prescription
    audit.prescriptionDate = datetime.now()
    audit.idDepartment = 1
    audit.idSegment = 1
    audit.totalItens = 1
    audit.agg = True
    audit.concilia = None
    audit.bed = "101"
    audit.extra = {}
    audit.createdAt = created_at
    audit.createdBy = created_by

    session.add(audit)
    session_commit()


def _set_review_type(id_prescription: int, review_type: int) -> None:
    """Flag a prescription's review status directly, leaving no trail."""
    session.execute(
        text(
            "UPDATE demo.prescricao SET tp_revisao = :review_type "
            "WHERE fkprescricao = :id"
        ),
        {"review_type": review_type, "id": id_prescription},
    )
    session_commit()


@pytest.fixture
def agg_prescription() -> tuple[int, int]:
    """An aggregated prescription with one drug, not yet reviewed.

    Returns ``(id_prescription, admission_number)``.
    """
    admission = test_counters["admission_number"]
    id_agg = test_counters["id_prescription"]
    id_internal = id_agg + 1

    test_counters["id_prescription"] += 2
    test_counters["admission_number"] += 1

    date = datetime.now()

    create_prescription(
        id=id_agg, admissionNumber=admission, idPatient=1, agg=True, date=date
    )
    create_prescription(
        id=id_internal, admissionNumber=admission, idPatient=1, date=date
    )
    create_prescription_drug(
        id=int(f"{id_internal}001"), idPrescription=id_internal, idDrug=3
    )

    return id_agg, admission


def test_view_shows_who_reviewed_the_patient(client, analyst_headers, agg_prescription):
    """After a review, the view names the reviewer and the time of the review."""
    id_agg, _ = agg_prescription

    _review(client, analyst_headers, id_agg, REVIEWED)

    review = _view(client, analyst_headers, id_agg)["review"]

    audit = (
        session.query(PrescriptionAudit)
        .filter(PrescriptionAudit.idPrescription == id_agg)
        .filter(PrescriptionAudit.auditType == PrescriptionAuditTypeEnum.REVISION.value)
        .one()
    )

    assert review["reviewed"] is True
    assert review["reviewedBy"] == CALLER_NAME
    assert review["reviewedAt"] == audit.createdAt.isoformat()


def test_view_shows_the_latest_review(client, analyst_headers, agg_prescription):
    """Of several REVISION rows, the most recent one names the reviewer."""
    id_agg, admission = agg_prescription
    now = datetime.now().replace(microsecond=0)
    latest = now - timedelta(hours=1)

    _set_review_type(id_agg, REVIEWED)
    # inserted out of order, so the answer cannot come from insertion order
    _add_audit(
        id_agg,
        admission,
        PrescriptionAuditTypeEnum.REVISION.value,
        created_by=CURATOR_USER_ID,
        created_at=latest,
    )
    _add_audit(
        id_agg,
        admission,
        PrescriptionAuditTypeEnum.REVISION.value,
        created_by=ADMIN_USER_ID,
        created_at=now - timedelta(days=1),
    )

    review = _view(client, analyst_headers, id_agg)["review"]

    assert review["reviewed"] is True
    assert review["reviewedBy"] == CURATOR_USER_NAME
    assert review["reviewedAt"] == latest.isoformat()


def test_view_ignores_undo_revisions_when_naming_the_reviewer(
    client, analyst_headers, agg_prescription
):
    """A later UNDO_REVISION row is not the review: the REVISION signs it."""
    id_agg, admission = agg_prescription
    now = datetime.now().replace(microsecond=0)
    reviewed_at = now - timedelta(days=2)

    _set_review_type(id_agg, REVIEWED)
    _add_audit(
        id_agg,
        admission,
        PrescriptionAuditTypeEnum.REVISION.value,
        created_by=ADMIN_USER_ID,
        created_at=reviewed_at,
    )
    _add_audit(
        id_agg,
        admission,
        PrescriptionAuditTypeEnum.UNDO_REVISION.value,
        created_by=CURATOR_USER_ID,
        created_at=now - timedelta(days=1),
    )

    review = _view(client, analyst_headers, id_agg)["review"]

    assert review["reviewedBy"] == ADMIN_USER_NAME
    assert review["reviewedAt"] == reviewed_at.isoformat()


def test_view_clears_the_review_after_it_is_undone(
    client, analyst_headers, agg_prescription
):
    """Undoing the review hides the reviewer even though the REVISION remains."""
    id_agg, _ = agg_prescription

    _review(client, analyst_headers, id_agg, REVIEWED)
    _review(client, analyst_headers, id_agg, PENDING)

    review = _view(client, analyst_headers, id_agg)["review"]

    assert review == {"reviewed": False, "reviewedBy": None, "reviewedAt": None}


def test_view_of_a_reviewed_prescription_without_a_trail(
    client, analyst_headers, agg_prescription
):
    """Reviewed with no REVISION row: flagged as reviewed, nobody to name."""
    id_agg, _ = agg_prescription

    _set_review_type(id_agg, REVIEWED)

    review = _view(client, analyst_headers, id_agg)["review"]

    assert review == {"reviewed": True, "reviewedBy": None, "reviewedAt": None}
