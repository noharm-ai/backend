"""Tests: patient observation history (GET /patient/<admission_number>/observation-history).

Covers ``patient_service.get_patient_observation_history``, which replays the
``pessoa_audit`` records of type OBSERVATION_RECORD written by
``patient_service.save_patient`` every time the free-text observation of a
patient actually changes.
"""

from models.enums import PatientAuditTypeEnum
from models.prescription import PatientAudit
from tests.conftest import session, session_commit
from tests.utils.utils_test_prescription import create_basic_prescription

DEMO_USER_NAME = "Demonstração"


def _history_url(admission_number):
    return f"/patient/{admission_number}/observation-history"


def _new_admission():
    """Create a prescription so that an admission number exists to attach a patient to."""
    return create_basic_prescription().admissionNumber


def _save_observation(client, headers, admission_number, observation):
    """Write the patient observation through the regular save endpoint."""
    return client.post(
        f"/patient/{admission_number}",
        json={"observation": observation},
        headers=headers,
    )


def _get_history(client, headers, admission_number):
    """Read the observation history for an admission."""
    response = client.get(_history_url(admission_number), headers=headers)
    assert response.status_code == 200

    return response.get_json()["data"]


def test_observation_history_requires_read_prescription(client, user_manager_headers):
    """A user without READ_PRESCRIPTION cannot read the history [401 UNAUTHORIZED]."""
    response = client.get(_history_url(_new_admission()), headers=user_manager_headers)

    assert response.status_code == 401


def test_observation_history_empty_for_admission_without_records(
    client, analyst_headers
):
    """An admission that never had an observation returns an empty history."""
    assert _get_history(client, analyst_headers, _new_admission()) == []


def test_observation_history_records_the_saved_observation(client, analyst_headers):
    """Saving an observation adds one entry with its text, author and timestamp."""
    admission_number = _new_admission()

    response = _save_observation(
        client, analyst_headers, admission_number, "primeira observação"
    )
    assert response.status_code == 200

    history = _get_history(client, analyst_headers, admission_number)
    assert len(history) == 1

    entry = history[0]
    assert entry["text"] == "primeira observação"
    assert entry["createdBy"] == DEMO_USER_NAME
    assert entry["createdAt"] is not None
    assert entry["id"] is not None


def test_observation_history_skips_unchanged_observation(client, analyst_headers):
    """Re-saving the same text does not add a second entry."""
    admission_number = _new_admission()

    _save_observation(client, analyst_headers, admission_number, "mesma observação")
    _save_observation(client, analyst_headers, admission_number, "mesma observação")

    assert len(_get_history(client, analyst_headers, admission_number)) == 1


def test_observation_history_returns_newest_first(client, analyst_headers):
    """Successive changes are listed from the most recent to the oldest."""
    admission_number = _new_admission()

    for observation in ["primeira", "segunda", "terceira"]:
        assert (
            _save_observation(
                client, analyst_headers, admission_number, observation
            ).status_code
            == 200
        )

    history = _get_history(client, analyst_headers, admission_number)

    assert [entry["text"] for entry in history] == ["terceira", "segunda", "primeira"]
    assert [entry["createdAt"] for entry in history] == sorted(
        [entry["createdAt"] for entry in history], reverse=True
    )


def test_observation_history_records_a_cleared_observation(client, analyst_headers):
    """Clearing the observation is a change too, so it is kept in the history."""
    admission_number = _new_admission()

    _save_observation(client, analyst_headers, admission_number, "a remover")
    assert (
        _save_observation(client, analyst_headers, admission_number, None).status_code
        == 200
    )

    history = _get_history(client, analyst_headers, admission_number)

    assert len(history) == 2
    assert history[0]["text"] is None
    assert history[1]["text"] == "a remover"


def test_observation_history_ignores_other_audit_types(client, analyst_headers):
    """Only OBSERVATION_RECORD audits show up — a plain patient update does not."""
    admission_number = _new_admission()

    response = client.post(
        f"/patient/{admission_number}",
        json={"height": "170.0"},
        headers=analyst_headers,
    )
    assert response.status_code == 200

    # the save did write an audit record, just not an observation one
    session.expire_all()
    audits = (
        session.query(PatientAudit)
        .filter(PatientAudit.admissionNumber == admission_number)
        .all()
    )
    assert [a.auditType for a in audits] == [PatientAuditTypeEnum.UPSERT.value]

    assert _get_history(client, analyst_headers, admission_number) == []


def test_observation_history_is_scoped_to_the_admission(client, analyst_headers):
    """Each admission only sees its own observations."""
    first = _new_admission()
    second = _new_admission()

    _save_observation(client, analyst_headers, first, "observação do primeiro")
    _save_observation(client, analyst_headers, second, "observação do segundo")

    assert [e["text"] for e in _get_history(client, analyst_headers, first)] == [
        "observação do primeiro"
    ]
    assert [e["text"] for e in _get_history(client, analyst_headers, second)] == [
        "observação do segundo"
    ]


def test_observation_history_empty_when_save_is_denied(client, viewer_headers):
    """A viewer cannot save an observation, so nothing reaches the history."""
    admission_number = _new_admission()

    response = _save_observation(
        client, viewer_headers, admission_number, "não deve gravar"
    )
    assert response.status_code == 401

    session_commit()

    # the viewer can still read the (empty) history
    assert _get_history(client, viewer_headers, admission_number) == []
