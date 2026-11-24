"""Tests: infection control lite mode (INFECTION_CONTROL_LITE alone)

Only what the infection control report's DOT/LOT needs: prescalc follows the
admissions revised, without reasons and without queueing them, and the job
entry (the nightly lite run of backend-private) runs the rule with nothing to
review, keeping the record's status and summary. INFECTION_CONTROL wins when
both are on, and a schema with neither is skipped by the job.
"""

import json
from unittest.mock import patch

from models.enums import FeatureEnum, InfectionControlResolutionEnum
from security.role import Role
from services.infection_control import infection_control_status_service as rule
from static import infection_control_sync
from tests.conftest import get_access, make_headers, session_commit
from tests.integration.infection_control.conftest import (
    _read_features,
    _write_features,
)
from tests.integration.infection_control.helpers import (
    CLOSED,
    NEVER_REVIEWED,
    NO_EVALUATION,
    PENDING,
    REVISED,
    _open_pendings,
    _pendings,
    _prescribe,
    _prescribe_today,
    _queued,
    _record,
    _set,
    _suspend,
    _day,
)
from utils import status

NOT_REQUIRED = InfectionControlResolutionEnum.NOT_REQUIRED.value
REPORT_URL = "/reports/consolidated/infection-control"


def _sync(admission_number):
    """Call the job entry for one admission, as backend-private does"""
    response = json.loads(
        infection_control_sync(
            {"schema": "demo", "admission_number": admission_number}, None
        )
    )
    session_commit()

    assert response["status"] == "success", response
    return response["data"]


def _summary(admission_number):
    """The report summary kept on the admission record"""
    return _record(admission_number)["resumo_acompanhamento"]


def _set_features(features):
    """Replace the demo schema's features (restored by the mode fixture)"""
    _write_features(features)


def test_prescalc_follows_revised_without_reasons(infection_control_lite, admission):
    """Prescalc creates the record revised, without the never reviewed reason
    and without queueing it for the light run"""
    _prescribe_today(admission, job=False)

    record = _record(admission)
    assert record["tp_status"] == REVISED
    assert record["indicadores"] is None
    assert _pendings(admission) == []
    assert _queued(admission) is None


def test_prescalc_reopens_closed_record_revised(infection_control_lite, admission):
    """A closed record whose antimicrobial restarts is reopened revised"""
    id_prescription = _prescribe_today(admission, job=False)
    _sync(admission)
    _suspend(id_prescription)
    assert _sync(admission) == "changed"
    assert _record(admission)["tp_status"] == CLOSED

    _prescribe_today(admission, job=False)

    assert _record(admission)["tp_status"] == REVISED
    assert _pendings(admission) == []


def test_job_keeps_summary_without_reasons(infection_control_lite, admission):
    """The job keeps the record revised, opens no reason and writes the
    summary the report reads"""
    _prescribe_today(admission, job=False)

    assert _sync(admission) == "processed"

    record = _record(admission)
    assert record["tp_status"] == REVISED
    assert _pendings(admission) == []
    summary = _summary(admission)
    assert [c["ongoing"] for c in summary["courses"]] == [True]
    # nothing is reviewed in lite: the report must not count it as missing a review
    assert [c["reviewRequired"] for c in summary["courses"]] == [False]
    assert summary["days"]


def test_job_closes_when_drug_stops(infection_control_lite, admission):
    """A stopped drug closes the record and ends its course in the summary"""
    id_prescription = _prescribe_today(admission, job=False)
    _sync(admission)
    _suspend(id_prescription)

    assert _sync(admission) == "changed"

    assert _record(admission)["tp_status"] == CLOSED
    assert [c["ongoing"] for c in _summary(admission)["courses"]] == [False]


def test_job_follows_admission_prescalc_missed(infection_control_lite, admission):
    """An admission with a running course and no record gets one, revised"""
    _prescribe(admission, _day(-1), _day(1))

    assert _sync(admission) == "changed"

    assert _record(admission)["tp_status"] == REVISED
    assert _pendings(admission) == []


def test_job_resolves_reasons_left_by_the_full_mode(infection_control, admission):
    """A schema moved from the full mode to the lite one: the open reasons are
    resolved as not required and the record is revised"""
    _prescribe_today(admission)
    assert _record(admission)["tp_status"] == PENDING
    assert _open_pendings(admission)

    _set_features(
        [f for f in _read_features() if f != FeatureEnum.INFECTION_CONTROL.value]
        + [FeatureEnum.INFECTION_CONTROL_LITE.value]
    )
    assert _sync(admission) == "changed"

    assert _record(admission)["tp_status"] == REVISED
    assert _open_pendings(admission) == []
    assert {p["tp_resolucao"] for p in _pendings(admission)} == {NOT_REQUIRED}


def test_full_mode_takes_over_a_lite_record(infection_control_lite, admission):
    """A schema moved from the lite mode to the full one: the next run opens
    the reasons of the record never reviewed"""
    _prescribe_today(admission, job=False)
    _sync(admission)
    assert _pendings(admission) == []

    _set_features(_read_features() + [FeatureEnum.INFECTION_CONTROL.value])
    assert _sync(admission) == "changed"

    assert _record(admission)["tp_status"] == PENDING
    open_types = {p["tp_pendencia"] for p in _open_pendings(admission)}
    assert {NEVER_REVIEWED, NO_EVALUATION} <= open_types


def test_full_mode_wins_over_lite(infection_control, admission):
    """With both features on, the full rule runs"""
    _set_features(_read_features() + [FeatureEnum.INFECTION_CONTROL_LITE.value])
    _prescribe_today(admission, job=False)
    assert NEVER_REVIEWED in {p["tp_pendencia"] for p in _open_pendings(admission)}

    assert _sync(admission) == "processed"

    assert NO_EVALUATION in {p["tp_pendencia"] for p in _open_pendings(admission)}
    assert _record(admission)["tp_status"] == PENDING


def test_job_skips_schema_without_either_mode(infection_control_lite, admission):
    """A schema with neither feature is skipped, its record left as it was"""
    _prescribe_today(admission, job=False)
    _sync(admission)
    before = _record(admission)

    _set_features(
        [f for f in _read_features() if f != FeatureEnum.INFECTION_CONTROL_LITE.value]
    )
    _suspend(_prescribe_today(admission, job=False))

    assert _sync(admission) == "skipped"
    assert _record(admission)["dt_recalculo"] == before["dt_recalculo"]


def test_report_open_in_lite_mode(client, infection_control_lite):
    """The report is open in the lite mode to READ_INFECTION_CONTROL [200 OK]"""
    headers = make_headers(get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value]))

    response = client.post(REPORT_URL, json={"year": 2026}, headers=headers)

    assert response.status_code == status.HTTP_200_OK


def test_job_reads_no_exams_or_cultures(infection_control_lite, admission):
    """The lite rule reads neither the exams cache nor the culture summary"""
    _prescribe_today(admission, job=False)

    with (
        patch.object(rule.exam_trigger_service, "load_results") as load_results,
        patch.object(rule.culture_trigger_service, "load_cultures") as load_cultures,
    ):
        assert _sync(admission) == "processed"

    load_results.assert_not_called()
    load_cultures.assert_not_called()


def test_courses_ended_in_lite_keep_no_review_after_moving_up(
    infection_control_lite, admission
):
    """A course that ended in the lite mode keeps reviewRequired false once the
    schema moves up to the full mode, so its review indicators count only
    what the full mode could review"""
    # a course started a week ago (the record is created while it runs), then
    # moved to end before today's one starts
    _prescribe(admission, _day(-8), _day(1))
    _sync(admission)
    _set("prescricao", admission, dtvigencia=_day(-6))
    _sync(admission)
    assert [c["reviewRequired"] for c in _summary(admission)["courses"]] == [False]

    _set_features(_read_features() + [FeatureEnum.INFECTION_CONTROL.value])
    _prescribe_today(admission, job=False)
    _sync(admission)

    courses = _summary(admission)["courses"]
    assert [(c["ongoing"], c["reviewRequired"]) for c in courses] == [
        (False, False),
        (True, True),
    ]
