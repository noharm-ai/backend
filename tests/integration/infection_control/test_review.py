"""Tests: infection control follow-up, the review save: permissions, evaluations,
superseding, backdating and validation"""

from datetime import datetime, timedelta

import pytest

from models.enums import (
    AntimicrobialEvaluationClosingEnum,
    AntimicrobialEvaluationStatusEnum,
    InfectionControlResolutionEnum,
)
from tests.integration.infection_control.helpers import (
    ANTIMICROBIAL_DRUG,
    CLOSED,
    EXPIRED,
    NEVER_REVIEWED,
    NO_EVALUATION,
    OTHER_DRUG,
    PENDING,
    REVISED,
    _day,
    _evaluations,
    _open_pendings,
    _pendings,
    _prescribe,
    _prescribe_today,
    _record,
    _review,
    _run_job,
    _set,
    _suspend,
)
from utils import status


def test_review_requires_permission(
    client, analyst_headers, infection_control, admission
):
    """401 without WRITE_INFECTION_CONTROL"""
    _prescribe_today(admission)

    response = _review(
        client, analyst_headers, admission, evaluations=[ANTIMICROBIAL_DRUG]
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_review_requires_token(client, infection_control, admission):
    """401 without a token"""
    response = client.post(
        "/infection-control/review", json={"admissionNumber": admission}
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_review_requires_feature(client, infection_controller_headers, admission):
    """400 when the schema does not have the feature"""
    _prescribe_today(admission)

    response = _review(client, infection_controller_headers, admission)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.businessRules"


def test_full_review_revises_admission(
    client, infection_controller_headers, infection_control, admission
):
    """Evaluating every running drug settles every reason"""
    _prescribe_today(admission)
    next_review = (datetime.now() + timedelta(days=3)).replace(microsecond=0)

    response = _review(
        client,
        infection_controller_headers,
        admission,
        evaluations=[ANTIMICROBIAL_DRUG],
        notes="Paciente estável",
        next_review_date=next_review.isoformat(),
    )

    assert response.status_code == status.HTTP_200_OK, response.get_json()
    data = response.get_json()["data"]
    assert data["status"] == REVISED
    assert data["pendings"] == []
    assert data["nextReviewDate"] == next_review.isoformat()
    assert data["reviews"][0]["notes"] == "Paciente estável"

    course = data["courses"][0]
    assert course["idDrug"] == ANTIMICROBIAL_DRUG
    assert course["ongoing"] is True
    assert course["evaluation"]["conforming"] is True
    assert course["evaluation"]["posology"]["dose"] == 2.0
    assert course["evaluation"]["posology"]["dailyFrequency"] is not None

    resolutions = {p["tp_pendencia"]: p["tp_resolucao"] for p in _pendings(admission)}
    assert resolutions == {
        NEVER_REVIEWED: InfectionControlResolutionEnum.REVIEW_SAVED.value,
        NO_EVALUATION: InfectionControlResolutionEnum.EVALUATED.value,
    }


def test_partial_review_keeps_admission_pending(
    client, infection_controller_headers, infection_control, admission
):
    """A review that evaluates nothing settles only 'never reviewed'"""
    _prescribe_today(admission)

    response = _review(client, infection_controller_headers, admission)

    assert response.status_code == status.HTTP_200_OK
    data = response.get_json()["data"]
    assert data["status"] == PENDING
    assert [p["type"] for p in data["pendings"]] == [NO_EVALUATION]


def test_reevaluation_supersedes_previous(
    client, infection_controller_headers, infection_control, admission
):
    """Evaluating the same course again supersedes the evaluation in force"""
    _prescribe_today(admission)
    _review(
        client,
        infection_controller_headers,
        admission,
        evaluations=[ANTIMICROBIAL_DRUG],
    )
    _review(
        client,
        infection_controller_headers,
        admission,
        evaluations=[ANTIMICROBIAL_DRUG],
    )

    first, second = _evaluations(admission)
    assert first["tp_status"] == AntimicrobialEvaluationStatusEnum.SUPERSEDED.value
    assert (
        first["tp_encerramento"] == AntimicrobialEvaluationClosingEnum.SUPERSEDED.value
    )
    assert first["fkci_avaliacao_atm_substituta"] == second["idci_avaliacao_atm"]
    assert second["tp_status"] == AntimicrobialEvaluationStatusEnum.ACTIVE.value
    assert _record(admission)["tp_status"] == REVISED


def test_overlapping_backdated_evaluation_supersedes_previous(
    client, infection_controller_headers, infection_control, admission
):
    """A backdated evaluation whose period reaches the one in force replaces
    it"""
    _prescribe_today(admission)
    _review(client, infection_controller_headers, admission, [ANTIMICROBIAL_DRUG])
    _review(
        client,
        infection_controller_headers,
        admission,
        evaluations=[ANTIMICROBIAL_DRUG],
        valid_from=_day(-1).isoformat(),
    )

    first, second = _evaluations(admission)
    assert first["tp_status"] == AntimicrobialEvaluationStatusEnum.SUPERSEDED.value
    assert first["fkci_avaliacao_atm_substituta"] == second["idci_avaliacao_atm"]
    assert second["tp_status"] == AntimicrobialEvaluationStatusEnum.ACTIVE.value


def test_evaluation_over_before_the_one_in_force_goes_to_history(
    client, infection_controller_headers, infection_control, admission
):
    """A period over before the evaluation in force starts is recorded as
    history: the evaluation in force and its reasons stay as they are"""
    _prescribe_today(admission)
    _review(
        client,
        infection_controller_headers,
        admission,
        evaluations=[ANTIMICROBIAL_DRUG],
        triggers=[EXPIRED],
    )
    # the evaluation in force expired: the admission is pending for it
    _set(
        "ci_avaliacao_atm", admission, dt_validade=datetime.now() - timedelta(minutes=1)
    )
    _run_job(admission)
    assert _record(admission)["tp_status"] == PENDING

    response = _review(
        client,
        infection_controller_headers,
        admission,
        evaluations=[ANTIMICROBIAL_DRUG],
        valid_from=_day(-1).isoformat(),
        valid_until=(_day(-1) + timedelta(hours=2)).isoformat(),
        triggers=[EXPIRED],
    )

    assert response.status_code == status.HTTP_200_OK, response.get_json()
    in_force, past = _evaluations(admission)
    assert in_force["tp_status"] == AntimicrobialEvaluationStatusEnum.ACTIVE.value
    assert in_force["fkci_avaliacao_atm_substituta"] is None
    assert past["tp_status"] == AntimicrobialEvaluationStatusEnum.CLOSED.value
    assert (
        past["tp_encerramento"] == AntimicrobialEvaluationClosingEnum.RETROACTIVE.value
    )
    # the expired one in force still keeps the admission pending
    assert _record(admission)["tp_status"] == PENDING
    (pending,) = _open_pendings(admission)
    assert pending["tp_pendencia"] == EXPIRED
    assert pending["fkci_avaliacao_atm"] == in_force["idci_avaliacao_atm"]

    course = response.get_json()["data"]["courses"][0]
    assert course["evaluation"]["id"] == str(in_force["idci_avaliacao_atm"])
    assert [e["id"] for e in course["history"]] == [
        str(past["idci_avaliacao_atm"]),
        str(in_force["idci_avaliacao_atm"]),
    ]


def test_suspended_drug_is_settled_on_save(
    client, infection_controller_headers, infection_control, admission
):
    """A drug suspended before being evaluated stops keeping the patient pending"""
    _suspend(_prescribe_today(admission))

    response = _review(client, infection_controller_headers, admission)

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"]["status"] == CLOSED
    no_evaluation = next(
        p for p in _pendings(admission) if p["tp_pendencia"] == NO_EVALUATION
    )
    assert (
        no_evaluation["tp_resolucao"]
        == InfectionControlResolutionEnum.DRUG_NO_LONGER_ACTIVE.value
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        # validity over before the evaluation starts
        {"valid_until": (datetime.now() - timedelta(hours=1)).isoformat()},
        {
            "valid_from": _day(-1).isoformat(),
            "valid_until": (_day(-1) - timedelta(hours=1)).isoformat(),
        },
        {"next_review_date": (datetime.now() - timedelta(hours=1)).isoformat()},
    ],
)
def test_review_rejects_invalid_dates(
    client, infection_controller_headers, infection_control, admission, kwargs
):
    """Validity ends after the evaluation starts; the next review is ahead"""
    _prescribe_today(admission)

    response = _review(
        client,
        infection_controller_headers,
        admission,
        evaluations=[ANTIMICROBIAL_DRUG],
        **kwargs,
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.invalidParams"
    assert _evaluations(admission) == []


def test_retroactive_evaluation_is_recorded_already_expired(
    client, infection_controller_headers, infection_control, admission
):
    """A backdated evaluation may have its validity over already: watching its
    expiry, it sends the admission straight back to pending"""
    _prescribe_today(admission)
    valid_until = datetime.now() - timedelta(hours=1)

    response = _review(
        client,
        infection_controller_headers,
        admission,
        evaluations=[ANTIMICROBIAL_DRUG],
        valid_from=_day(-1).isoformat(),
        valid_until=valid_until.isoformat(),
        triggers=[EXPIRED],
    )

    assert response.status_code == status.HTTP_200_OK, response.get_json()
    (evaluation,) = _evaluations(admission)
    assert evaluation["dt_validade"] == valid_until
    assert _record(admission)["tp_status"] == PENDING
    (pending,) = _open_pendings(admission)
    assert pending["tp_pendencia"] == EXPIRED
    assert pending["fkci_avaliacao_atm"] == evaluation["idci_avaliacao_atm"]


def test_retroactive_evaluation_without_expiry_trigger_revises(
    client, infection_controller_headers, infection_control, admission
):
    """Without watching its expiry, a retroactive evaluation settles the drug"""
    _prescribe_today(admission)

    response = _review(
        client,
        infection_controller_headers,
        admission,
        evaluations=[ANTIMICROBIAL_DRUG],
        valid_from=_day(-1).isoformat(),
        valid_until=(datetime.now() - timedelta(hours=1)).isoformat(),
    )

    assert response.status_code == status.HTTP_200_OK, response.get_json()
    assert _record(admission)["tp_status"] == REVISED
    assert _open_pendings(admission) == []


def test_evaluation_applies_from_the_review_by_default(
    client, infection_controller_headers, infection_control, admission
):
    """Without a start, the evaluation applies from the moment it is saved"""
    _prescribe_today(admission)

    response = _review(
        client,
        infection_controller_headers,
        admission,
        evaluations=[ANTIMICROBIAL_DRUG],
    )

    assert response.status_code == status.HTTP_200_OK, response.get_json()
    evaluation = response.get_json()["data"]["courses"][0]["evaluation"]
    assert evaluation["validFrom"] == evaluation["createdAt"]
    row = _evaluations(admission)[0]
    assert row["dt_inicio_validade"] == row["created_at"]


def test_evaluation_can_be_backdated_to_the_course_start(
    client, infection_controller_headers, infection_control, admission
):
    """The infectologist may date the verdict back to the start of the course"""
    _prescribe_today(admission)

    response = _review(
        client,
        infection_controller_headers,
        admission,
        evaluations=[ANTIMICROBIAL_DRUG],
        valid_from=_day(-1).isoformat(),
    )

    assert response.status_code == status.HTTP_200_OK, response.get_json()
    course = response.get_json()["data"]["courses"][0]
    assert course["evaluation"]["validFrom"] == course["start"]
    assert course["evaluation"]["validFrom"] == _day(-1).isoformat()
    assert _evaluations(admission)[0]["dt_inicio_validade"] == _day(-1)


@pytest.mark.parametrize(
    "valid_from",
    [
        # before the course
        lambda: _day(-2),
        # in the future
        lambda: datetime.now() + timedelta(hours=1),
    ],
)
def test_review_rejects_start_outside_the_course_until_now(
    client, infection_controller_headers, infection_control, admission, valid_from
):
    """An evaluation starts between its course start and now"""
    _prescribe_today(admission)

    response = _review(
        client,
        infection_controller_headers,
        admission,
        evaluations=[ANTIMICROBIAL_DRUG],
        valid_from=valid_from().isoformat(),
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.invalidParams"
    assert _evaluations(admission) == []


def test_review_rejects_drug_not_running(
    client, infection_controller_headers, infection_control, admission
):
    """Only running antimicrobials can be evaluated"""
    _prescribe_today(admission)

    response = _review(
        client, infection_controller_headers, admission, evaluations=[OTHER_DRUG]
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert _evaluations(admission) == []


def test_review_rejects_admission_not_followed(
    client, infection_controller_headers, infection_control, admission
):
    """An admission is reviewed only once it is followed"""
    _prescribe(admission, _day(-1), _day(1))

    response = _review(
        client,
        infection_controller_headers,
        admission,
        evaluations=[ANTIMICROBIAL_DRUG],
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.invalidRecord"
    assert _record(admission) is None
