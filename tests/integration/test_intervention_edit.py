"""Tests: editing an intervention that already exists (PUT /intervention with
``idIntervention`` -> intervention_service.save_intervention).

The same endpoint that opens an intervention also edits it: when the body
carries ``idIntervention`` the service loads that record and rewrites it
instead of creating a new one. Editing is guarded, because an intervention is
evidence of the pharmacist's work and feeds the economy reports:

* the record has to exist;
* once an outcome was given (accepted, not accepted, not applicable,
  justified) the only change allowed is putting it back as pending ("s");
* an intervention whose prescription drug -- or, for a prescription-level
  intervention, whose prescription -- was archived can no longer be edited;
* this interface only saves pending ("s") or draft ("0") interventions; any
  other status is refused.

What an accepted edit keeps and what it rewrites is also pinned down: the
record is updated in place (no new row), the edit is audited as an UPDATE,
and the responsible pharmacist only changes when the caller asks for it.

Creating an intervention is covered by test_intervention.py and the outcome
rules by test_intervention_set_outcome_rules.py.
"""

from datetime import datetime

import pytest
from sqlalchemy import text

from models.enums import InterventionAuditEnum
from models.prescription import Intervention, InterventionAudit
from tests.conftest import session, session_commit
from tests.utils.utils_test_prescription import (
    create_prescription,
    create_prescription_drug,
    test_counters,
)
from utils import status

URL = "/intervention"

# seed reasons (demo.motivointervencao)
REASON_PLAIN = 5  # "Duplicidade medicamentosa" -- no economy
REASON_OTHER = 6

# an id that is never created
MISSING_ID = 999999

# a user id that is not the logged-in analyst, to tell the responsible apart
OTHER_USER_ID = 987654


@pytest.fixture(autouse=True)
def clean_interventions():
    """Drop the interventions this module writes -- tests.conftest does not know them."""
    yield
    session.execute(
        text(
            "DELETE FROM demo.intervencao_audit WHERE idintervencao IN "
            "(SELECT idintervencao FROM demo.intervencao WHERE nratendimento >= 100000)"
        )
    )
    session.execute(text("DELETE FROM demo.intervencao WHERE nratendimento >= 100000"))
    session_commit()


def _prescription_with_drug():
    """Create a prescription with one drug and return (admission, prescription, drug)."""
    id_prescription = test_counters["id_prescription"]
    test_counters["id_prescription"] += 1
    admission = test_counters["admission_number"]
    test_counters["admission_number"] += 1

    create_prescription(
        id=id_prescription,
        admissionNumber=admission,
        idPatient=1,
        date=datetime.now(),
        idDepartment=1,
    )

    id_prescription_drug = int(f"{id_prescription}001")
    create_prescription_drug(
        id=id_prescription_drug,
        idPrescription=id_prescription,
        idDrug=3,
    )

    return admission, id_prescription, id_prescription_drug


def _open_drug_intervention(client, headers):
    """Open a pending intervention on a fresh prescription drug.

    Returns (id_intervention, admission, id_prescription_drug).
    """
    admission, _, id_prescription_drug = _prescription_with_drug()

    response = client.put(
        URL,
        json={
            "status": "s",
            "admissionNumber": admission,
            "idInterventionReason": [REASON_PLAIN],
            "idPrescriptionDrug": str(id_prescription_drug),
            "observation": "observacao original",
        },
        headers=headers,
    )
    assert response.status_code == status.HTTP_200_OK

    return (
        response.get_json()["data"][0]["idIntervention"],
        admission,
        id_prescription_drug,
    )


def _open_prescription_intervention(client, headers):
    """Open a pending intervention on a whole prescription.

    Returns (id_intervention, admission, id_prescription).
    """
    admission, id_prescription, _ = _prescription_with_drug()

    response = client.put(
        URL,
        json={
            "status": "s",
            "admissionNumber": admission,
            "idInterventionReason": [REASON_PLAIN],
            "idPrescription": id_prescription,
            "idPrescriptionDrug": "0",
        },
        headers=headers,
    )
    assert response.status_code == status.HTTP_200_OK

    return response.get_json()["data"][0]["idIntervention"], admission, id_prescription


def _edit(client, headers, id_intervention, **extra):
    """PUT an edit of an existing intervention."""
    body = {"idIntervention": id_intervention, "status": "s"}
    body.update(extra)
    return client.put(URL, json=body, headers=headers)


def _intervention(id_intervention) -> Intervention:
    """Reload an intervention from the database, bypassing the session cache."""
    session.expire_all()
    return (
        session.query(Intervention)
        .filter(Intervention.idIntervention == id_intervention)
        .first()
    )


def _set_columns(id_intervention, **columns):
    """Write intervention columns directly, as another flow would have."""
    session.query(Intervention).filter(
        Intervention.idIntervention == id_intervention
    ).update(columns, synchronize_session=False)
    session_commit()


def test_edit_updates_the_record_in_place(client, analyst_headers):
    """An edit rewrites the fields it carries and creates no new row [200]."""
    id_intervention, admission, _ = _open_drug_intervention(client, analyst_headers)

    response = _edit(
        client,
        analyst_headers,
        id_intervention,
        idInterventionReason=[REASON_OTHER],
        observation="observacao editada",
        error=True,
        cost=True,
    )

    assert response.status_code == status.HTTP_200_OK
    data = response.get_json()["data"]
    assert len(data) == 1
    assert data[0]["idIntervention"] == id_intervention

    record = _intervention(id_intervention)
    assert record.idInterventionReason == [REASON_OTHER]
    assert record.notes == "observacao editada"
    assert record.error is True
    assert record.cost is True
    assert record.status == "s"

    count = (
        session.query(Intervention)
        .filter(Intervention.admissionNumber == admission)
        .count()
    )
    assert count == 1


def test_edit_is_audited_as_an_update(client, analyst_headers):
    """The edit leaves an UPDATE audit row after the CREATE one."""
    id_intervention, _, _ = _open_drug_intervention(client, analyst_headers)

    response = _edit(client, analyst_headers, id_intervention, observation="nova")
    assert response.status_code == status.HTTP_200_OK

    session.expire_all()
    audit_types = [
        a.auditType
        for a in session.query(InterventionAudit)
        .filter(InterventionAudit.idIntervention == id_intervention)
        .order_by(InterventionAudit.id)
        .all()
    ]
    assert audit_types == [
        InterventionAuditEnum.CREATE.value,
        InterventionAuditEnum.UPDATE.value,
    ]


def test_edit_omitting_fields_keeps_them(client, analyst_headers):
    """Fields left out of the body are not wiped by the edit [200]."""
    id_intervention, _, _ = _open_drug_intervention(client, analyst_headers)

    response = _edit(client, analyst_headers, id_intervention, error=True)
    assert response.status_code == status.HTTP_200_OK

    record = _intervention(id_intervention)
    assert record.notes == "observacao original"
    assert record.idInterventionReason == [REASON_PLAIN]


def test_edit_keeps_the_responsible_unless_asked(client, analyst_headers):
    """The responsible only moves to the editor when updateResponsible is set."""
    id_intervention, _, _ = _open_drug_intervention(client, analyst_headers)
    _set_columns(id_intervention, user=OTHER_USER_ID)

    response = _edit(client, analyst_headers, id_intervention, observation="a")
    assert response.status_code == status.HTTP_200_OK
    assert _intervention(id_intervention).user == OTHER_USER_ID

    response = _edit(
        client,
        analyst_headers,
        id_intervention,
        observation="b",
        updateResponsible=True,
    )
    assert response.status_code == status.HTTP_200_OK
    assert _intervention(id_intervention).user != OTHER_USER_ID


def test_draft_promoted_to_pending_is_restamped(client, analyst_headers):
    """A draft ("0") saved as pending takes the editor and today as its date [200]."""
    id_intervention, _, _ = _open_drug_intervention(client, analyst_headers)
    old_date = datetime(2020, 1, 1)
    _set_columns(id_intervention, status="0", user=OTHER_USER_ID, date=old_date)

    response = _edit(client, analyst_headers, id_intervention)

    assert response.status_code == status.HTTP_200_OK
    record = _intervention(id_intervention)
    assert record.status == "s"
    assert record.user != OTHER_USER_ID
    assert record.date.date() == datetime.today().date()


def test_edit_of_an_unknown_intervention_is_refused(client, analyst_headers):
    """An idIntervention that does not exist is an invalid record [400]."""
    response = _edit(client, analyst_headers, MISSING_ID)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.invalidRecord"


@pytest.mark.parametrize("outcome", ["a", "n", "x", "j"])
def test_intervention_with_outcome_cannot_change_status(
    client, analyst_headers, outcome
):
    """With an outcome, any status other than pending is refused [400]."""
    id_intervention, _, _ = _open_drug_intervention(client, analyst_headers)
    _set_columns(id_intervention, status=outcome)

    response = _edit(client, analyst_headers, id_intervention, status="0")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.invalidRecord"
    assert _intervention(id_intervention).status == outcome


def test_intervention_with_outcome_can_be_reopened_as_pending(client, analyst_headers):
    """Putting an intervention with an outcome back as pending is allowed [200]."""
    id_intervention, _, _ = _open_drug_intervention(client, analyst_headers)
    _set_columns(id_intervention, status="a")

    response = _edit(client, analyst_headers, id_intervention, status="s")

    assert response.status_code == status.HTTP_200_OK
    assert _intervention(id_intervention).status == "s"


@pytest.mark.parametrize("new_status", ["a", "n", "x", "j"])
def test_outcome_cannot_be_applied_through_this_interface(
    client, analyst_headers, new_status
):
    """Outcomes have their own endpoint; this one refuses them [400]."""
    id_intervention, _, _ = _open_drug_intervention(client, analyst_headers)

    response = _edit(client, analyst_headers, id_intervention, status=new_status)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.invalidRecord"
    assert _intervention(id_intervention).status == "s"


def test_intervention_on_an_archived_drug_cannot_be_edited(client, analyst_headers):
    """Once its prescription drug is archived the intervention is frozen [400]."""
    id_intervention, _, id_prescription_drug = _open_drug_intervention(
        client, analyst_headers
    )
    session.execute(
        text("DELETE FROM demo.presmed WHERE fkpresmed = :id"),
        {"id": id_prescription_drug},
    )
    session_commit()

    response = _edit(client, analyst_headers, id_intervention, observation="x")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.businessRules"
    assert _intervention(id_intervention).notes == "observacao original"


def test_intervention_on_an_archived_prescription_cannot_be_edited(
    client, analyst_headers
):
    """A prescription-level intervention freezes once its prescription is archived [400]."""
    id_intervention, _, id_prescription = _open_prescription_intervention(
        client, analyst_headers
    )
    session.execute(
        text("DELETE FROM demo.presmed WHERE fkprescricao = :id"),
        {"id": id_prescription},
    )
    session.execute(
        text("DELETE FROM demo.prescricao WHERE fkprescricao = :id"),
        {"id": id_prescription},
    )
    session_commit()

    response = _edit(client, analyst_headers, id_intervention, observation="x")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.businessRules"


def test_prescription_intervention_can_be_edited(client, analyst_headers):
    """A prescription-level intervention is edited like a drug-level one [200]."""
    id_intervention, _, id_prescription = _open_prescription_intervention(
        client, analyst_headers
    )

    response = _edit(
        client, analyst_headers, id_intervention, observation="prescricao editada"
    )

    assert response.status_code == status.HTTP_200_OK
    record = _intervention(id_intervention)
    assert record.notes == "prescricao editada"
    assert record.idPrescription == id_prescription
    assert record.id == 0


def test_viewer_cannot_edit(client, analyst_headers, viewer_headers):
    """Editing needs WRITE_PRESCRIPTION [401]."""
    id_intervention, _, _ = _open_drug_intervention(client, analyst_headers)

    response = _edit(client, viewer_headers, id_intervention, observation="x")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert _intervention(id_intervention).notes == "observacao original"
