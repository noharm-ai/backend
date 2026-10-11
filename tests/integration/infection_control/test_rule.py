"""Tests: infection control follow-up, the rule applied by the scheduled job: reasons, stops,
discharge and the optional triggers"""

from datetime import datetime, timedelta

from models.enums import (
    AntimicrobialEvaluationStatusEnum,
    InfectionControlOriginEnum,
    InfectionControlResolutionEnum,
)
from tests.integration.infection_control.helpers import (
    ANTIMICROBIAL_DRUG,
    CLOSED,
    EXPIRED,
    NEVER_REVIEWED,
    NO_EVALUATION,
    PENDING,
    POSOLOGY_CHANGED,
    REVISED,
    SCHEDULED_DATE,
    _day,
    _discharge,
    _evaluations,
    _open_pendings,
    _pendings,
    _prescalc,
    _prescribe,
    _prescribe_today,
    _record,
    _review,
    _run_job,
    _set,
    _suspend,
)
from utils import status


def test_rule_opens_reasons_of_each_drug(infection_control, admission):
    """The rule opens a reason for each running drug without an evaluation"""
    id_prescription = _prescribe_today(admission, job=False)

    _run_job(admission)

    pendings = _open_pendings(admission)
    assert [p["tp_pendencia"] for p in pendings] == [NEVER_REVIEWED, NO_EVALUATION]
    assert pendings[1]["fkmedicamento"] == ANTIMICROBIAL_DRUG
    assert pendings[1]["fkprescricao"] == id_prescription
    assert pendings[1]["tp_origem"] == InfectionControlOriginEnum.JOB.value
    assert _record(admission)["tp_status"] == PENDING


def test_new_antimicrobial_reopens_revised_admission(
    client,
    infection_controller_headers,
    infection_control,
    admission,
    second_antimicrobial,
):
    """A new antimicrobial on a revised patient makes it pending again once
    the job runs"""
    _prescribe_today(admission)
    _review(
        client,
        infection_controller_headers,
        admission,
        evaluations=[ANTIMICROBIAL_DRUG],
    )
    assert _record(admission)["tp_status"] == REVISED

    _prescribe_today(
        admission, drugs=(ANTIMICROBIAL_DRUG, second_antimicrobial), job=False
    )
    assert _record(admission)["tp_status"] == REVISED

    _run_job(admission)

    assert _record(admission)["tp_status"] == PENDING
    pendings = _open_pendings(admission)
    assert [(p["tp_pendencia"], p["fkmedicamento"]) for p in pendings] == [
        (NO_EVALUATION, second_antimicrobial)
    ]


def test_rule_closes_admission_when_drug_stops(infection_control, admission):
    """A suspended drug resolves its reasons and closes the admission"""
    _suspend(_prescribe_today(admission))

    _run_job(admission)

    assert _record(admission)["tp_status"] == CLOSED
    assert _open_pendings(admission) == []
    assert {p["tp_resolucao"] for p in _pendings(admission)} == {
        InfectionControlResolutionEnum.DRUG_NO_LONGER_ACTIVE.value
    }


def test_rule_closes_admission_on_discharge(
    client, infection_controller_headers, infection_control, admission
):
    """Discharge closes the admission, its evaluations and its reasons"""
    _prescribe_today(admission)
    _review(client, infection_controller_headers, admission)
    _discharge(admission)

    _run_job(admission)

    assert _record(admission)["tp_status"] == CLOSED
    assert {p["tp_resolucao"] for p in _pendings(admission) if p["tp_resolucao"]} >= {
        InfectionControlResolutionEnum.DISCHARGE.value
    }
    assert _open_pendings(admission) == []


def _reviewed(client, headers, admission_number, **kwargs):
    """An admission on an antimicrobial, evaluated and revised"""
    _prescribe_today(admission_number)
    response = _review(
        client, headers, admission_number, evaluations=[ANTIMICROBIAL_DRUG], **kwargs
    )
    assert response.status_code == status.HTTP_200_OK, response.get_json()
    assert _record(admission_number)["tp_status"] == REVISED


def test_expired_evaluation_sends_admission_back_to_pending(
    client, infection_controller_headers, infection_control, admission
):
    """A running drug whose evaluation watches its expiry and is past its
    validity is pending again, until it is evaluated again"""
    _reviewed(client, infection_controller_headers, admission, triggers=[EXPIRED])
    (evaluation,) = _evaluations(admission)
    _set("ci_avaliacao_atm", admission, dt_validade=datetime.now() - timedelta(hours=1))

    _run_job(admission)

    assert _record(admission)["tp_status"] == PENDING
    (pending,) = _open_pendings(admission)
    assert pending["tp_pendencia"] == EXPIRED
    assert pending["fkmedicamento"] == ANTIMICROBIAL_DRUG
    assert pending["fkci_avaliacao_atm"] == evaluation["idci_avaliacao_atm"]

    # a review that doesn't evaluate the drug again leaves it pending
    _review(client, infection_controller_headers, admission)
    assert _record(admission)["tp_status"] == PENDING

    _review(
        client,
        infection_controller_headers,
        admission,
        evaluations=[ANTIMICROBIAL_DRUG],
        triggers=[EXPIRED],
    )
    assert _record(admission)["tp_status"] == REVISED
    expired = next(p for p in _pendings(admission) if p["tp_pendencia"] == EXPIRED)
    assert expired["tp_resolucao"] == InfectionControlResolutionEnum.EVALUATED.value


def test_expiry_is_ignored_without_the_trigger(
    client, infection_controller_headers, infection_control, admission
):
    """An evaluation that doesn't watch its expiry stays in force past it"""
    _reviewed(client, infection_controller_headers, admission)
    _set("ci_avaliacao_atm", admission, dt_validade=datetime.now() - timedelta(hours=1))

    _run_job(admission)

    assert _record(admission)["tp_status"] == REVISED
    assert _open_pendings(admission) == []


def test_posology_change_sends_watching_evaluation_back_to_pending(
    client, infection_controller_headers, infection_control, admission
):
    """A new dose of a drug evaluated with the posology trigger is pending again"""
    _reviewed(
        client,
        infection_controller_headers,
        admission,
        triggers=[POSOLOGY_CHANGED],
    )
    assert _evaluations(admission)[0]["gatilhos"] == [POSOLOGY_CHANGED]

    _prescalc(_prescribe(admission, _day(0), _day(2), dose=4.0))
    _run_job(admission)

    assert _record(admission)["tp_status"] == PENDING
    (pending,) = _open_pendings(admission)
    assert pending["tp_pendencia"] == POSOLOGY_CHANGED
    assert pending["detalhes"]["evaluated"]["dose"] == 2.0
    assert pending["detalhes"]["current"]["dose"] == 4.0

    response = _review(
        client,
        infection_controller_headers,
        admission,
        evaluations=[ANTIMICROBIAL_DRUG],
        triggers=[POSOLOGY_CHANGED],
    )
    data = response.get_json()["data"]
    assert data["status"] == REVISED
    assert data["courses"][0]["evaluation"]["triggers"] == [POSOLOGY_CHANGED]
    assert data["courses"][0]["evaluation"]["posology"]["dose"] == 4.0


def test_posology_change_is_ignored_without_the_trigger(
    client, infection_controller_headers, infection_control, admission
):
    """An evaluation that doesn't watch the posology stays in force"""
    _reviewed(client, infection_controller_headers, admission)

    _prescalc(_prescribe(admission, _day(0), _day(2), dose=4.0))
    _run_job(admission)

    assert _record(admission)["tp_status"] == REVISED
    assert _open_pendings(admission) == []


def test_daily_prescription_with_same_posology_is_not_a_change(
    client, infection_controller_headers, infection_control, admission
):
    """The next day's prescription repeating the posology changes nothing"""
    _reviewed(
        client,
        infection_controller_headers,
        admission,
        triggers=[POSOLOGY_CHANGED],
    )

    _prescalc(_prescribe(admission, _day(0), _day(2)))
    _run_job(admission)

    assert _record(admission)["tp_status"] == REVISED
    assert _open_pendings(admission) == []


def test_scheduled_review_date_sends_admission_back_to_pending(
    client, infection_controller_headers, infection_control, admission
):
    """The scheduled review date arriving makes the patient pending until a
    review is saved"""
    _reviewed(
        client,
        infection_controller_headers,
        admission,
        next_review_date=(datetime.now() + timedelta(days=3)).isoformat(),
    )
    _set(
        "ci_atendimento",
        admission,
        dt_proxima_revisao=datetime.now() - timedelta(hours=1),
    )

    _run_job(admission)

    assert _record(admission)["tp_status"] == PENDING
    assert [p["tp_pendencia"] for p in _open_pendings(admission)] == [SCHEDULED_DATE]

    _review(client, infection_controller_headers, admission)

    assert _record(admission)["tp_status"] == REVISED
    assert _record(admission)["dt_proxima_revisao"] is None
    scheduled = next(
        p for p in _pendings(admission) if p["tp_pendencia"] == SCHEDULED_DATE
    )
    assert (
        scheduled["tp_resolucao"] == InfectionControlResolutionEnum.REVIEW_SAVED.value
    )


def test_restarted_course_drops_reasons_of_the_old_evaluation(
    client, infection_controller_headers, infection_control, admission
):
    """When the drug runs in a new course, the old course's evaluation closes
    with its reasons and the new course needs an evaluation"""
    _reviewed(client, infection_controller_headers, admission, triggers=[EXPIRED])
    _set("ci_avaliacao_atm", admission, dt_validade=datetime.now() - timedelta(hours=1))
    _run_job(admission)
    (expired,) = _open_pendings(admission)

    # the evaluation now belongs to a course that is over
    _set("ci_avaliacao_atm", admission, dt_inicio_curso=_day(-9))
    _run_job(admission)

    assert _evaluations(admission)[0]["tp_status"] == (
        AntimicrobialEvaluationStatusEnum.CLOSED.value
    )
    resolved = next(
        p
        for p in _pendings(admission)
        if p["idci_pendencia"] == expired["idci_pendencia"]
    )
    assert (
        resolved["tp_resolucao"]
        == InfectionControlResolutionEnum.DRUG_NO_LONGER_ACTIVE.value
    )
    assert [p["tp_pendencia"] for p in _open_pendings(admission)] == [NO_EVALUATION]
    assert _record(admission)["tp_status"] == PENDING


def test_review_rejects_unknown_trigger(
    client, infection_controller_headers, infection_control, admission
):
    """Only the optional reasons can be chosen as triggers"""
    _prescribe_today(admission)

    response = _review(
        client,
        infection_controller_headers,
        admission,
        evaluations=[ANTIMICROBIAL_DRUG],
        triggers=[NEVER_REVIEWED],
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.invalidParams"
