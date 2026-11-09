"""Unit tests for the infection control exam triggers
(services.infection_control.exam_trigger_service and the rules' model,
models.infection_control_config).

A rule the evaluation turned on opens a reason of the drug (EXAM_RESULT) when
a result the reviewer could not have seen (after the baseline, or after the
evaluation without one) meets every condition it sets.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from models.enums import InfectionControlPendingTypeEnum, InfectionControlStatusEnum
from models.infection_control_config import (
    ExamTriggerRuleInput,
    parse_exam_trigger_rules,
)
from services.infection_control import exam_trigger_service as exam_triggers
from services.infection_control import infection_control_status_service as rule
from services.infection_control.antimicrobial_timeline_service import (
    build_item,
    group_courses,
)
from tests.unit.test_infection_control_status_rule import _row

NOW = datetime(2026, 10, 7, 14, 0)
COURSE_START = NOW - timedelta(days=5)
REVIEWED_AT = NOW - timedelta(days=2)
ADULT = exam_triggers.PatientData(birthdate=datetime(1970, 5, 4), gender="F")

PCR_RISE = {
    "id": "pcr-rise",
    "name": "PCR subiu",
    "examRef": "pcru",
    "valueAbove": 1.5,
    "variationAbove": 30,
    "fromCourseDay": None,
}
FEVER_AFTER_D3 = {
    "id": "fever",
    "name": "Febre após D3",
    "examRef": "temp",
    "valueAbove": 38,
    "fromCourseDay": 4,
}
EGFR_FALL = {
    "id": "egfr-fall",
    "name": "TFG caiu",
    "examRef": "ckd21",
    "valueBelow": 60,
    "variationBelow": -25,
    "fromCourseDay": None,
}


def _baseline(value, date=REVIEWED_AT - timedelta(hours=6), **extra):
    """A baseline as the evaluation keeps it"""
    return {"examType": "pcr", "date": date.isoformat(), "value": value, **extra}


def _evaluation(*triggers, created_at=REVIEWED_AT):
    """An evaluation with these exam triggers among its triggers (gatilhos)"""
    return SimpleNamespace(
        id=7,
        triggers=[1, *({"type": "exam", **t} for t in triggers)],
        created_at=created_at,
    )


def _course(start=COURSE_START):
    """A course started at `start`"""
    return SimpleNamespace(start=start)


def _results(by_ref, patient=ADULT):
    """The results of each reference: (date, value)"""
    return exam_triggers.ExamResults(
        by_ref={
            ref: [
                exam_triggers.ExamResult(
                    exam_type=ref, date=date, raw_value=value, unit=None
                )
                for date, value in results
            ]
            for ref, results in by_ref.items()
        },
        patient=patient,
    )


def _match_ids(evaluation, results, course=None):
    """The ids of the rules matched"""
    return [
        m["id"]
        for m in exam_triggers.exam_matches(
            evaluation=evaluation, course=course or _course(), results=results, now=NOW
        )
    ]


# --- the rules' model ---


def test_a_rule_needs_a_name_an_exam_of_the_catalog_and_a_condition():
    """The users write the rules: anything else is refused"""
    ExamTriggerRuleInput.model_validate({**FEVER_AFTER_D3, "id": None})

    for invalid in (
        {**FEVER_AFTER_D3, "name": "  "},
        {**FEVER_AFTER_D3, "examRef": "creatinina"},
        {**FEVER_AFTER_D3, "valueAbove": None},
        {**FEVER_AFTER_D3, "fromCourseDay": 0},
    ):
        with pytest.raises(ValidationError):
            ExamTriggerRuleInput.model_validate(invalid)


def test_the_reference_is_matched_in_lower_case():
    """The catalog keeps the references in lower case"""
    assert ExamTriggerRuleInput.model_validate(
        {**FEVER_AFTER_D3, "examRef": " TEMP "}
    ).examRef == ("temp")


def test_kept_rules_drop_invalid_ones_on_their_own():
    """A rule kept invalid (or repeating an id, or without one) is left out;
    the others still apply"""
    rules = parse_exam_trigger_rules(
        [
            PCR_RISE,
            {**FEVER_AFTER_D3, "examRef": "x"},
            {**EGFR_FALL, "id": "pcr-rise"},
            {**EGFR_FALL, "id": None},
            EGFR_FALL,
        ]
    )

    assert [r.id for r in rules] == ["pcr-rise", "egfr-fall"]
    assert parse_exam_trigger_rules(None) == []
    assert parse_exam_trigger_rules("x") == []


# --- matching ---


def test_value_and_rise_over_the_baseline():
    """Both conditions on one result: over 1.5 and more than 30% over the
    baseline"""
    evaluation = _evaluation({**PCR_RISE, "baseline": _baseline(1.2)})

    # 1.6 is 33% over 1.2
    assert _match_ids(
        evaluation, _results({"pcru": [(NOW - timedelta(hours=3), 1.6)]})
    ) == ["pcr-rise"]
    # over 1.5 but only 25% over the baseline
    assert (
        _match_ids(evaluation, _results({"pcru": [(NOW - timedelta(hours=3), 1.5)]}))
        == []
    )


def test_inclusive_conditions():
    """AtLeast / AtMost hold on the limit itself; Above / Below don't"""
    pcr = {
        **PCR_RISE,
        "examRef": "pcru",
        "variationAbove": None,
        "valueAbove": 50,
        "variationAtLeast": 20,
    }

    def matched(trigger, value, baseline=50):
        evaluation = _evaluation({**trigger, "baseline": _baseline(baseline)})
        results = _results({"pcru": [(NOW - timedelta(hours=1), value)]})
        return _match_ids(evaluation, results) == [trigger["id"]]

    # exactly 20% over 50
    assert matched(pcr, 60)
    assert not matched(pcr, 59.9)
    # 50 is not over 50, even rising 25%
    assert not matched(pcr, 50, baseline=40)
    assert matched({**pcr, "valueAbove": None, "valueAtLeast": 50}, 50, baseline=40)
    # a fall to at most 30
    fall = {**pcr, "valueAbove": None, "variationAtLeast": None, "valueAtMost": 30}
    assert matched(fall, 30)
    assert not matched(fall, 30.1)
    assert matched({**fall, "valueAtMost": None, "variationAtMost": -40}, 30)


def test_match_details():
    """The reason names the rule, the result, the baseline and the variation"""
    baseline = _baseline(1.0)
    evaluation = _evaluation({**PCR_RISE, "baseline": baseline})
    date = NOW - timedelta(hours=3)

    [match] = exam_triggers.exam_matches(
        evaluation=evaluation,
        course=_course(),
        results=_results({"pcru": [(date, 2.0)]}),
        now=NOW,
    )

    assert match == {
        "id": "pcr-rise",
        "name": "PCR subiu",
        "examRef": "pcru",
        "result": {
            "examType": "pcru",
            "date": date.isoformat(),
            "value": 2.0,
            "unit": None,
        },
        "baseline": baseline,
        "variation": 100.0,
    }


def test_only_results_after_the_baseline_count():
    """A result the reviewer had seen (up to the baseline) never fires: a new
    evaluation doesn't reopen the reason on the result that opened it"""
    evaluation = _evaluation({**PCR_RISE, "baseline": _baseline(2.0, date=REVIEWED_AT)})
    results = _results({"pcru": [(REVIEWED_AT, 2.0)]})

    assert _match_ids(evaluation, results) == []


def test_a_late_result_dated_before_the_review_counts():
    """A result dated after the baseline arriving later was not seen: it counts
    even if dated before the evaluation was made"""
    evaluation = _evaluation(
        {
            **PCR_RISE,
            "baseline": _baseline(1.0, date=REVIEWED_AT - timedelta(days=1)),
        }
    )
    results = _results({"pcru": [(REVIEWED_AT - timedelta(hours=2), 1.8)]})

    assert _match_ids(evaluation, results) == ["pcr-rise"]


def test_without_a_baseline():
    """A variation is not met without a baseline; a value-only rule counts the
    results after the evaluation was made"""
    rise = _evaluation({**PCR_RISE, "baseline": None})
    fever = _evaluation({**FEVER_AFTER_D3, "baseline": None})

    assert _match_ids(rise, _results({"pcru": [(NOW - timedelta(hours=1), 5)]})) == []
    assert _match_ids(
        fever, _results({"temp": [(NOW - timedelta(hours=1), 38.5)]})
    ) == ["fever"]
    assert (
        _match_ids(
            fever,
            _results({"temp": [(REVIEWED_AT - timedelta(hours=1), 39)]}),
        )
        == []
    )


def test_from_course_day():
    """Fever after D3: a result on D3 doesn't count, one on D4 does (D1 is the
    first 24 hours of the course)"""
    start = NOW - timedelta(days=3, hours=12)
    evaluation = _evaluation(
        {**FEVER_AFTER_D3, "baseline": None},
        created_at=start + timedelta(hours=1),
    )
    course = _course(start)

    on_d3 = start + timedelta(days=2, hours=12)
    on_d4 = start + timedelta(days=3, hours=1)
    assert _match_ids(evaluation, _results({"temp": [(on_d3, 39)]}), course) == []
    assert _match_ids(evaluation, _results({"temp": [(on_d4, 38.1)]}), course) == [
        "fever"
    ]
    # 38 is not over 38
    assert _match_ids(evaluation, _results({"temp": [(on_d4, 38)]}), course) == []


def test_calculated_egfr_fall():
    """CKD-EPI 2021 calculated from the creatinine, with the patient's age and
    gender: a fall of more than 25% from the baseline to below 60"""
    baseline_egfr = exam_triggers.calc_value("ckd21", 0.8, ADULT)
    evaluation = _evaluation(
        {**EGFR_FALL, "baseline": _baseline(baseline_egfr, rawValue=0.8)}
    )

    worse = _results({"ckd21": [(NOW - timedelta(hours=2), 1.4)]})
    slightly = _results({"ckd21": [(NOW - timedelta(hours=2), 0.9)]})

    assert _match_ids(evaluation, worse) == ["egfr-fall"]
    assert _match_ids(evaluation, slightly) == []

    [match] = exam_triggers.exam_matches(
        evaluation=evaluation, course=_course(), results=worse, now=NOW
    )
    assert match["result"]["rawValue"] == 1.4
    assert match["result"]["value"] < 60
    assert match["result"]["unit"] == "ml/min/1.73"


def test_ckd_uses_the_patient_measures():
    """CKD-EPI (2009) is adjusted by the height and weight when known"""
    plain = exam_triggers.calc_value("ckd", 1.0, ADULT)
    adjusted = exam_triggers.calc_value(
        "ckd",
        1.0,
        exam_triggers.PatientData(
            birthdate=ADULT.birthdate, gender="F", height=150, weight=50
        ),
    )

    assert plain and adjusted and plain != adjusted


def test_ckd_is_calculated_only_for_adults():
    """Without a birthdate, or for a child, there is no CKD (the exams screen
    uses Schwartz then): it never fires"""
    evaluation = _evaluation({**EGFR_FALL, "baseline": _baseline(90)})
    child = exam_triggers.PatientData(
        birthdate=datetime.now() - timedelta(days=365 * 10), gender="F"
    )

    for patient in (exam_triggers.PatientData(), child):
        results = _results({"ckd21": [(NOW - timedelta(hours=2), 3.0)]}, patient)
        assert _match_ids(evaluation, results) == []
    assert exam_triggers.calc_value("ckd21", 3.0, child) is None


def test_other_exams_compare_the_result():
    """Any other reference compares the result as it is"""
    assert exam_triggers.calc_value("pcru", 12.30000001, ADULT) == 12.3
    assert exam_triggers.calc_value("pcru", None, ADULT) is None


def test_the_first_result_that_meets_and_every_rule():
    """Each rule is reported once, with the first result that met it"""
    evaluation = _evaluation(
        {**PCR_RISE, "baseline": _baseline(1.0)},
        {**FEVER_AFTER_D3, "baseline": None},
    )
    first = NOW - timedelta(hours=10)
    results = _results(
        {
            "pcru": [(first, 1.6), (NOW - timedelta(hours=1), 2.5)],
            "temp": [(NOW - timedelta(hours=1), 39)],
        }
    )

    matches = exam_triggers.exam_matches(
        evaluation=evaluation, course=_course(), results=results, now=NOW
    )

    assert [m["id"] for m in matches] == ["pcr-rise", "fever"]
    assert matches[0]["result"]["date"] == first.isoformat()


def test_no_exam_triggers():
    """An evaluation without exam triggers (or no results loaded) gives none"""
    assert (
        exam_triggers.exam_matches(
            evaluation=_evaluation(), course=_course(), results=_results({}), now=NOW
        )
        == []
    )
    assert (
        exam_triggers.exam_matches(
            evaluation=_evaluation({**FEVER_AFTER_D3, "baseline": None}),
            course=_course(),
            results=None,
            now=NOW,
        )
        == []
    )


def test_results_from_the_exams_cache(monkeypatch):
    """The rule reads the latest result of each watched exam from the cache
    (tpexame in any case); an entry without a value or a valid date is left
    out"""
    monkeypatch.setattr(
        exam_triggers.patient_repository,
        "get_patient_by_admission",
        lambda admission_number: SimpleNamespace(
            idPatient=7,
            birthdate=ADULT.birthdate,
            gender="F",
            skinColor=None,
            height=None,
            weight=None,
        ),
    )
    monkeypatch.setattr(
        exam_triggers,
        "exam_sources",
        lambda refs: {"pcru": {"pcr", "pcr2"}, "temp": {"tax"}},
    )
    keys = []

    def cached(key):
        """The cached hash of the patient"""
        keys.append(key)
        return {
            "PCR": {"value": 80, "unit": "mg/L", "date": "2026-10-07T10:00:00"},
            "pcr2": {"value": 60, "unit": None, "date": "2026-10-06T10:00:00-03:00"},
            "TAX": {"value": None, "date": "2026-10-07T10:00:00"},
        }

    monkeypatch.setattr(
        exam_triggers.exams_repository.cache_service, "get_hgetall", cached
    )

    results = exam_triggers.load_results(
        admission_number=1,
        schema="demo",
        evaluations=[
            _evaluation(
                {**PCR_RISE, "baseline": None}, {**FEVER_AFTER_D3, "baseline": None}
            )
        ],
    )

    assert keys == ["demo:7:exames"]
    assert [(r.exam_type, r.raw_value, r.date) for r in results.results("pcru")] == [
        ("pcr2", 60, datetime(2026, 10, 6, 10)),
        ("pcr", 80, datetime(2026, 10, 7, 10)),
    ]
    assert results.results("temp") == []
    assert exam_triggers._cached_result("pcr", {"value": 1, "date": "x"}) is None


# --- the rule ---


def test_the_rule_opens_an_exam_result_reason():
    """A met rule opens one reason of the drug, naming the matches; the
    patient goes back to pending"""
    [course] = group_courses(
        [build_item(_row(date=COURSE_START, expire=NOW + timedelta(days=1)), now=NOW)]
    )
    evaluation = SimpleNamespace(
        id=7,
        id_drug=1,
        course_start=course.start,
        valid_until=NOW + timedelta(days=5),
        triggers=[{"type": "exam", **FEVER_AFTER_D3, "baseline": None}],
        posology=None,
        conforming=True,
        created_at=REVIEWED_AT,
    )

    plan = rule.plan_rule(
        ongoing=[course],
        discharged=False,
        id_last_review=1,
        active_evaluations=[evaluation],
        open_pendings=[],
        now=NOW,
        exam_results=_results({"temp": [(NOW - timedelta(hours=1), 38.6)]}),
    )

    [pending] = plan.open_pendings
    assert pending["pending_type"] == InfectionControlPendingTypeEnum.EXAM_RESULT
    assert pending["id_drug"] == 1
    assert pending["id_evaluation"] == 7
    assert [m["id"] for m in pending["details"]["matches"]] == ["fever"]
    assert plan.status == InfectionControlStatusEnum.PENDING


def test_exam_triggers_are_kept_among_the_triggers():
    """gatilhos keeps the pending types (ints) and the exam triggers
    (objects): each reader takes its own"""
    evaluation = _evaluation({**FEVER_AFTER_D3, "baseline": None})

    assert rule.pending_triggers(evaluation) == [1]
    assert [t["id"] for t in exam_triggers.evaluation_exam_triggers(evaluation)] == [
        "fever"
    ]
    assert rule.pending_triggers(SimpleNamespace(triggers=None)) == []


def test_a_new_evaluation_settles_the_exam_result_reason():
    """Like the other reasons of the drug, a new evaluation resolves it"""
    assert (
        InfectionControlPendingTypeEnum.EXAM_RESULT.value
        in rule.EVALUATION_RESOLVED_TYPES
    )
    # it is not one of the triggers list (gatilhos): the rules are kept apart
    assert InfectionControlPendingTypeEnum.EXAM_RESULT.value not in (
        rule.OPTIONAL_TRIGGERS
    )
