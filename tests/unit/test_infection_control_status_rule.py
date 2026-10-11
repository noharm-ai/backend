"""Unit tests for the infection control rule (services.infection_control.infection_control_status_service).

plan_rule decides, without the database, which evaluations close, which
pending reasons open or resolve and the admission status. The same rule runs
in the scheduled job of backend-private: the plan_rule cases here mirror the
rule and trigger tests of its tests/test_infection_control_service.py (same
names), so a change to the rule must keep both suites in step.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from models.enums import (
    AntimicrobialEvaluationClosingEnum,
    InfectionControlPendingTypeEnum,
    InfectionControlResolutionEnum,
    InfectionControlStatusEnum,
)
from services.infection_control import antimicrobial_timeline_service as timeline
from services.infection_control import infection_control_status_service as rule

NOW = datetime(2026, 10, 7, 14, 0)

PendingType = InfectionControlPendingTypeEnum
Resolution = InfectionControlResolutionEnum
Status = InfectionControlStatusEnum
Closing = AntimicrobialEvaluationClosingEnum

POSOLOGY = {
    "dose": 2.0,
    "doseconv": 2.0,
    "measureUnit": "g",
    "frequency": "8/8h",
    "dailyFrequency": 3.0,
    "route": "EV",
}
POSOLOGY_TRIGGER = [PendingType.POSOLOGY_CHANGED.value]
EXPIRED_TRIGGER = [PendingType.EXPIRED.value]


def _row(id_drug=1, date=None, expire=None, suspended_date=None, cpoe=False, **kwargs):
    """An antimicrobial row as returned by get_admission_antimicrobials"""
    return SimpleNamespace(
        id_prescription=kwargs.get("id_prescription", 10),
        id_prescription_drug=kwargs.get("id_prescription_drug", 100),
        id_drug=id_drug,
        drug=kwargs.get("drug", f"DRUG {id_drug}"),
        substance=None,
        atb_level=None,
        date=date,
        expire=expire,
        suspended_date=suspended_date,
        cpoe=cpoe,
        dose=kwargs.get("dose", 2.0),
        doseconv=kwargs.get("doseconv", kwargs.get("dose", 2.0)),
        measure_unit=kwargs.get("measure_unit", "g"),
        frequency=kwargs.get("frequency", "8/8h"),
        daily_frequency=kwargs.get("daily_frequency", 3.0),
        route=kwargs.get("route", "EV"),
        period_total=None,
    )


def _courses(*rows):
    """Group rows into courses at NOW"""
    return timeline.group_courses([timeline.build_item(r, now=NOW) for r in rows])


def _evaluation(id_evaluation, id_drug, course_start, **kwargs):
    """An active evaluation row"""
    return SimpleNamespace(
        id=id_evaluation,
        id_drug=id_drug,
        course_start=course_start,
        valid_until=kwargs.get("valid_until", NOW + timedelta(days=7)),
        posology=kwargs.get("posology", POSOLOGY),
        triggers=kwargs.get("triggers", []),
    )


def _pending(id_pending, pending_type, id_drug=None, id_evaluation=None):
    """An open pending row"""
    return SimpleNamespace(
        id=id_pending,
        pending_type=pending_type,
        id_drug=id_drug,
        id_evaluation=id_evaluation,
    )


def _running(id_drug=1, start=None):
    """A running daily course of one drug"""
    (course,) = _courses(
        _row(
            id_drug=id_drug,
            date=start or NOW - timedelta(hours=6),
            expire=NOW + timedelta(hours=18),
        )
    )
    return course


def _plan(course, evaluation, **kwargs):
    """Plan a reviewed admission with one running course and its evaluation"""
    return rule.plan_rule(
        now=NOW,
        ongoing=[course],
        discharged=False,
        id_last_review=7,
        active_evaluations=[evaluation],
        open_pendings=kwargs.get("open_pendings", []),
        next_review_date=kwargs.get("next_review_date"),
    )


def _reasons(plan):
    """Pending types the plan opens"""
    return [p["pending_type"] for p in plan.open_pendings]


def _prescribed(*rows):
    """The single running course of the given rows (same drug)"""
    (course,) = _courses(*rows)
    return course


def _today(**kwargs):
    """A row of today's prescription, running"""
    return _row(
        date=NOW - timedelta(hours=6), expire=NOW + timedelta(hours=18), **kwargs
    )


def _yesterday(**kwargs):
    """A row of yesterday's prescription"""
    return _row(
        id_prescription=9,
        date=NOW - timedelta(hours=30),
        expire=NOW - timedelta(hours=6),
        **kwargs,
    )


class TestIsOngoing:
    """When a course still counts as running"""

    def test_open_ended_cpoe_order_runs_until_now(self):
        """A CPOE order without expire date ends now, so it is running"""
        (course,) = _courses(_row(date=NOW - timedelta(days=4), cpoe=True))

        assert course.end == NOW
        assert rule.is_ongoing(course, NOW)

    def test_suspension_ends_the_item(self):
        """A suspension before the planned end ends the course at once"""
        suspended_at = NOW - timedelta(hours=1)
        (course,) = _courses(
            _row(
                date=NOW - timedelta(days=1),
                expire=NOW + timedelta(days=1),
                suspended_date=suspended_at,
            )
        )

        assert course.end == suspended_at
        assert course.last_item.suspended
        assert not rule.is_ongoing(course, NOW)

    def test_finished_course_runs_for_the_gap_tolerance(self):
        """A course that was not suspended is still running for 36h after its end"""
        (recent,) = _courses(
            _row(date=NOW - timedelta(days=2), expire=NOW - timedelta(hours=35))
        )
        (old,) = _courses(
            _row(date=NOW - timedelta(days=3), expire=NOW - timedelta(hours=37))
        )

        assert rule.is_ongoing(recent, NOW)
        assert not rule.is_ongoing(old, NOW)


class TestRule:
    """Reasons, evaluations closed and the status (mirrors backend-private)"""

    def test_rule_opens_never_reviewed_and_one_reason_per_drug(self):
        """A never reviewed admission gets its own reason plus one per running drug"""
        first, second = _running(1, NOW - timedelta(hours=8)), _running(2)

        plan = rule.plan_rule(
            now=NOW,
            ongoing=[first, second],
            discharged=False,
            id_last_review=None,
            active_evaluations=[],
            open_pendings=[_pending(1, PendingType.NEVER_REVIEWED)],
        )

        assert _reasons(plan) == [
            PendingType.NEVER_REVIEWED,
            PendingType.NO_EVALUATION,
            PendingType.NO_EVALUATION,
        ]
        assert [p.get("id_drug") for p in plan.open_pendings] == [None, 1, 2]
        assert plan.open_pendings[1]["details"] == {
            "drug": "DRUG 1",
            "courseStart": first.start.isoformat(),
        }
        assert plan.open_pendings[1]["id_prescription"] == 10
        assert plan.resolve_pendings == {}
        assert plan.status == Status.PENDING

    def test_rule_keeps_evaluated_course_revised(self):
        """A reviewed admission whose running course has an evaluation is revised"""
        course = _running(1)

        plan = _plan(course, _evaluation(50, 1, course.start))

        assert plan.open_pendings == []
        assert plan.close_evaluations == []
        assert plan.status == Status.REVISED

    def test_rule_new_drug_on_reviewed_admission_is_pending(self):
        """A new antimicrobial without an evaluation makes a revised admission pending"""
        evaluated, new = _running(1), _running(2)

        plan = rule.plan_rule(
            now=NOW,
            ongoing=[evaluated, new],
            discharged=False,
            id_last_review=7,
            active_evaluations=[_evaluation(50, 1, evaluated.start)],
            open_pendings=[],
        )

        assert [(p["pending_type"], p["id_drug"]) for p in plan.open_pendings] == [
            (PendingType.NO_EVALUATION, 2)
        ]
        assert plan.status == Status.PENDING

    def test_rule_evaluation_of_previous_course_is_closed(self):
        """An evaluation outside the running course closes as course ended and the
        drug needs a new one"""
        course = _running(1)

        plan = _plan(course, _evaluation(50, 1, course.start - timedelta(days=10)))

        assert plan.close_evaluations == [50]
        assert plan.closing_type == Closing.COURSE_ENDED
        assert [p["id_drug"] for p in plan.open_pendings] == [1]
        assert plan.status == Status.PENDING

    def test_rule_resolves_reasons_of_stopped_drug(self):
        """Reasons of a drug no longer running resolve while the others stay open"""
        course = _running(1)

        plan = _plan(
            course,
            _evaluation(50, 1, course.start),
            open_pendings=[
                _pending(1, PendingType.NO_EVALUATION, id_drug=2),
                # a reason without a drug is not tied to a course
                _pending(2, PendingType.SCHEDULED_DATE),
            ],
        )

        assert plan.resolve_pendings == {Resolution.DRUG_NO_LONGER_ACTIVE: [1]}
        assert plan.status == Status.PENDING

    def test_rule_closes_when_nothing_runs(self):
        """Without running courses every reason resolves as no longer active and
        the record closes"""
        plan = rule.plan_rule(
            now=NOW,
            ongoing=[],
            discharged=False,
            id_last_review=None,
            active_evaluations=[_evaluation(50, 1, NOW - timedelta(days=3))],
            open_pendings=[
                _pending(1, PendingType.NEVER_REVIEWED),
                _pending(2, PendingType.NO_EVALUATION, id_drug=1),
            ],
        )

        assert plan.open_pendings == []
        assert plan.close_evaluations == [50]
        assert plan.closing_type == Closing.COURSE_ENDED
        assert plan.resolve_pendings == {Resolution.DRUG_NO_LONGER_ACTIVE: [1, 2]}
        assert plan.status == Status.CLOSED

    def test_rule_closes_on_discharge(self):
        """Discharge closes evaluations and resolves reasons with the discharge type"""
        plan = rule.plan_rule(
            now=NOW,
            ongoing=[],
            discharged=True,
            id_last_review=7,
            active_evaluations=[_evaluation(50, 1, NOW - timedelta(days=3))],
            open_pendings=[_pending(2, PendingType.NO_EVALUATION, id_drug=1)],
        )

        assert plan.closing_type == Closing.DISCHARGE
        assert plan.resolve_pendings == {Resolution.DISCHARGE: [2]}
        assert plan.status == Status.CLOSED

    def test_rule_scheduled_review_date_is_pending_once_reached(self):
        """The scheduled review date makes the admission pending once it arrives"""
        course = _running(1)
        evaluation = _evaluation(50, 1, course.start)

        reached = _plan(course, evaluation, next_review_date=NOW - timedelta(minutes=1))
        ahead = _plan(course, evaluation, next_review_date=NOW + timedelta(days=1))

        assert _reasons(reached) == [PendingType.SCHEDULED_DATE]
        assert "id_drug" not in reached.open_pendings[0]
        assert reached.status == Status.PENDING
        assert ahead.open_pendings == []
        assert ahead.status == Status.REVISED

    def test_rule_restarted_course_drops_reasons_of_the_old_evaluation(self):
        """Reasons tied to an evaluation of a course that is over resolve, even with
        the drug running again"""
        course = _running(1)

        plan = _plan(
            course,
            _evaluation(50, 1, course.start - timedelta(days=10)),
            open_pendings=[
                _pending(1, PendingType.EXPIRED, id_drug=1, id_evaluation=50)
            ],
        )

        assert plan.close_evaluations == [50]
        assert plan.resolve_pendings == {Resolution.DRUG_NO_LONGER_ACTIVE: [1]}
        assert _reasons(plan) == [PendingType.NO_EVALUATION]
        assert plan.status == Status.PENDING


class TestTriggers:
    """Optional reasons an evaluation opts into (mirrors backend-private)"""

    def test_rule_expired_evaluation_is_pending_when_watched(self):
        """A running course whose evaluation watches its expiry and is past its
        validity is pending again"""
        course = _running(1)
        expired = NOW - timedelta(hours=1)

        watched = _plan(
            course,
            _evaluation(
                50, 1, course.start, valid_until=expired, triggers=EXPIRED_TRIGGER
            ),
        )
        unwatched = _plan(course, _evaluation(50, 1, course.start, valid_until=expired))

        assert _reasons(watched) == [PendingType.EXPIRED]
        assert watched.open_pendings[0]["id_evaluation"] == 50
        assert watched.open_pendings[0]["id_drug"] == 1
        assert watched.close_evaluations == []
        assert watched.status == Status.PENDING
        assert unwatched.open_pendings == []
        assert unwatched.status == Status.REVISED

    def test_rule_posology_change_is_pending_when_watched(self):
        """A new dose opens a reason only for an evaluation that watches the posology"""
        course = _prescribed(_yesterday(), _today(dose=4.0))

        watched = _plan(
            course, _evaluation(50, 1, course.start, triggers=POSOLOGY_TRIGGER)
        )
        unwatched = _plan(course, _evaluation(50, 1, course.start))

        assert _reasons(watched) == [PendingType.POSOLOGY_CHANGED]
        details = watched.open_pendings[0]["details"]
        assert details["evaluated"]["dose"] == 2.0
        assert details["current"]["dose"] == 4.0
        assert watched.open_pendings[0]["id_evaluation"] == 50
        assert watched.status == Status.PENDING
        assert unwatched.open_pendings == []
        assert unwatched.status == Status.REVISED

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"route": "VO"},
            {"daily_frequency": 4.0, "frequency": "6/6h"},
            # without a conversion the dose is compared as written, unit included
            {"doseconv": None, "measure_unit": "mg"},
        ],
    )
    def test_rule_posology_change_of_route_frequency_or_unit(self, kwargs):
        """Route, doses per day and the written unit are part of the posology"""
        course = _prescribed(_today(**kwargs))
        evaluated = {**POSOLOGY, "doseconv": None} if "doseconv" in kwargs else POSOLOGY

        plan = _plan(
            course,
            _evaluation(
                50, 1, course.start, triggers=POSOLOGY_TRIGGER, posology=evaluated
            ),
        )

        assert _reasons(plan) == [PendingType.POSOLOGY_CHANGED]

    def test_rule_same_posology_written_another_way_is_not_a_change(self):
        """The same converted dose and doses per day, written differently, change
        nothing"""
        course = _prescribed(
            _today(dose=2000.0, doseconv=2.0, measure_unit="mg", frequency="3x/dia ")
        )

        plan = _plan(
            course, _evaluation(50, 1, course.start, triggers=POSOLOGY_TRIGGER)
        )

        assert plan.open_pendings == []

    def test_rule_any_line_of_the_latest_prescription_keeps_the_posology(self):
        """A drug written in two lines (e.g. a loading dose) doesn't count as a change"""
        course = _prescribed(
            _today(id_prescription_drug=100),
            _today(id_prescription_drug=101, dose=4.0),
        )

        plan = _plan(
            course, _evaluation(50, 1, course.start, triggers=POSOLOGY_TRIGGER)
        )

        assert plan.open_pendings == []


class TestSamePosology:
    """Fallbacks of the posology comparison when converted values are missing"""

    def test_both_doses_missing_is_the_same_dose(self):
        """Two posologies without any dose don't differ on the dose"""
        evaluated = {**POSOLOGY, "dose": None, "doseconv": None}

        assert rule.same_posology(evaluated, dict(evaluated))

    def test_one_dose_missing_is_a_change(self):
        """A dose that appears or disappears is a change"""
        evaluated = {**POSOLOGY, "dose": None, "doseconv": None}

        assert not rule.same_posology(evaluated, POSOLOGY)

    @pytest.mark.parametrize(
        "current_frequency, same",
        [(" 8/8H ", True), ("12/12h", False)],
    )
    def test_frequency_as_written_without_doses_per_day(self, current_frequency, same):
        """Without doses per day the frequency is compared as written, ignoring
        case and spaces"""
        evaluated = {**POSOLOGY, "dailyFrequency": None}
        current = {**evaluated, "frequency": current_frequency}

        assert rule.same_posology(evaluated, current) is same
