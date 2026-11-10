"""Service: exam triggers of the infection control evaluations

The users define the exam trigger rules (models/infection_control_config.py,
kept in the schema's memoria): conditions on the results of an exam of the
catalog (EXAM_TRIGGER_EXAMS), named by its reference
(segmentoexame.tpexame_ref, normalized in every schema). CKD and CKD21 are not
results of their own: they are calculated from the creatinine with the
patient's data (CALCULATED_EXAMS). The reviewer turns the rules on per drug
evaluation; while the evaluation is in force, a result that meets every
condition of a rule opens a reason of the drug
(InfectionControlPendingTypeEnum.EXAM_RESULT), settled by a new evaluation.

* load_rules / save_rules: the rules kept in the memoria record. A schema
  that never defined them gets a copy of the global ones (public.memoria, same
  tipo) the first time they are read;
* snapshot (review save): each rule turned on is copied on the evaluation
  with its baseline, among its triggers (ci_avaliacao_atm.gatilhos, as an
  object with `type` TRIGGER_TYPE_EXAM next to the pending types), the latest
  result of the exam when the review is saved (from the exame table, or the
  DynamoDB archive when the table has none). Editing or deleting a rule never
  changes what an evaluation already watches;
* load_results (the rule): the results of the exams the evaluations in force
  watch, from the exams cache (Redis, the latest result of each exam, as
  prescalc reads it). A reference mapped to several exams (or the
  creatinines, for the CKDs) reads only the latest of them, as the prescription
  view and the protocols do;
* exam_matches (the rule, without the database): the rules a course's
  evaluation turned on that a result meets.

Only results the reviewer could not have seen count: dated after the baseline
(or after the evaluation was made, when it had none). So a new evaluation,
taking the latest result as its baseline, never reopens the reason on the
result that opened it. A variation is measured from the baseline and is not
met without one.

The rule reads only the cache: the exams cache job of backend-private, after
caching new results, queues the patient's followed admissions for the light run
of the job, so each update of the cache is seen soon after. The cache keeps the
latest result of each exam, so a result the cache replaced before the rule ran
(two results of the exam between updates) isn't seen.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from dateutil import parser

from models.appendix import GlobalMemory, Memory
from models.enums import MemoryEnum
from models.infection_control import AntimicrobialEvaluation
from models.infection_control_config import (
    CALCULATED_EXAMS,
    EXAM_TRIGGER_EXAMS,
    ExamTriggerRule,
    ExamTriggerRuleInput,
    parse_exam_trigger_rules,
)
from models.main import db
from repository import exams_repository, patient_repository
from services.infection_control.antimicrobial_timeline_service import (
    Course,
    started_days,
)
from utils import dateutils, examutils, logger

# the `type` of an exam trigger in the evaluation's triggers (gatilhos)
TRIGGER_TYPE_EXAM = "exam"
# CKD and CKD21 are adult formulas (the exams screen calculates them over 17)
CALCULATED_MIN_AGE = 18


@dataclass(frozen=True)
class PatientData:
    """What the calculated exams need of the patient"""

    birthdate: datetime | None = None
    gender: str | None = None
    skin_color: str | None = None
    height: float | None = None
    weight: float | None = None

    @classmethod
    def of(cls, patient) -> "PatientData":
        """The data of a patient record (none without one)"""
        if patient is None:
            return cls()
        return cls(
            birthdate=patient.birthdate,
            gender=patient.gender,
            skin_color=patient.skinColor,
            height=patient.height,
            weight=patient.weight,
        )


@dataclass(frozen=True)
class ExamResult:
    """A result of an exam (for a calculated exam, the creatinine)"""

    exam_type: str
    date: datetime
    raw_value: float
    unit: str | None


@dataclass
class ExamResults:
    """The results of the exam references the evaluations in force watch,
    oldest first (load_results keeps only the latest of each), and the patient
    the calculated exams need"""

    by_ref: dict[str, list[ExamResult]] = field(default_factory=dict)
    patient: PatientData = field(default_factory=PatientData)

    def results(self, exam_ref: str) -> list[ExamResult]:
        """The results of a reference"""
        return self.by_ref.get(exam_ref, [])


# --- the rules ---


def _rules_record() -> Memory | None:
    """The memoria record keeping the schema's rules"""
    return (
        db.session.query(Memory)
        .filter(Memory.kind == MemoryEnum.INFECTION_CONTROL_EXAM_TRIGGERS.value)
        .order_by(Memory.key)
        .first()
    )


def _global_rules() -> list[ExamTriggerRule]:
    """The rules NoHarm keeps in public.memoria for the schemas that never
    defined theirs: each keeps its id, or gets one when it has none (an
    invalid rule, or one repeating an id, is left out)"""
    record = (
        db.session.query(GlobalMemory)
        .filter(
            GlobalMemory.kind == MemoryEnum.INFECTION_CONTROL_EXAM_TRIGGERS.value
        )
        .order_by(GlobalMemory.key)
        .first()
    )
    if record is None or not isinstance(record.value, list):
        return []

    return parse_exam_trigger_rules(
        [
            {**item, "id": item.get("id") or uuid.uuid4().hex}
            for item in record.value
            if isinstance(item, dict)
        ]
    )


def load_rules(user_id: int, now: datetime) -> list[ExamTriggerRule]:
    """The schema's exam trigger rules. A schema that never defined them (no
    record: an empty list is a schema that removed them all) gets a copy of
    the global ones (public.memoria), saved as its own so the users edit them
    from then on; none when there are no global ones either"""
    record = _rules_record()
    if record is not None:
        return parse_exam_trigger_rules(record.value)

    rules = _global_rules()
    if not rules:
        return []

    record = Memory()
    record.kind = MemoryEnum.INFECTION_CONTROL_EXAM_TRIGGERS.value
    record.value = [rule.model_dump() for rule in rules]
    record.update = now
    record.user = user_id
    db.session.add(record)
    db.session.flush()

    return rules


def save_rules(
    rules: list[ExamTriggerRuleInput], user_id: int, now: datetime
) -> list[ExamTriggerRule]:
    """Replaces the schema's rules: a new rule gets an id, a kept one keeps
    its own (an id that isn't a rule of the schema raises ValueError)"""
    current_ids = {rule.id for rule in load_rules(user_id=user_id, now=now)}
    saved = []
    seen = set()
    for rule in rules:
        if rule.id is not None and (rule.id not in current_ids or rule.id in seen):
            raise ValueError(f"exam trigger rule not found: {rule.id}")

        id_rule = rule.id or uuid.uuid4().hex
        seen.add(id_rule)
        saved.append(ExamTriggerRule(**{**rule.model_dump(), "id": id_rule}))

    record = _rules_record()
    if record is None:
        record = Memory()
        record.kind = MemoryEnum.INFECTION_CONTROL_EXAM_TRIGGERS.value
        db.session.add(record)
    record.value = [rule.model_dump() for rule in saved]
    record.update = now
    record.user = user_id
    db.session.flush()

    return saved


# --- the exams ---


def exam_sources(exam_refs: set[str]) -> dict[str, set[str]]:
    """The exams of the schema (tpexame, lower case) whose results each
    reference reads: those mapped to it, or the creatinine for a calculated
    one"""
    sources: dict[str, set[str]] = {ref: set() for ref in exam_refs}

    mapped = exams_repository.get_exam_types_by_ref(exam_refs - CALCULATED_EXAMS)
    for exam_type, exam_ref in mapped.items():
        sources[exam_ref].add(exam_type)

    calculated = exam_refs & CALCULATED_EXAMS
    if calculated:
        creatinine = exams_repository.get_creatinine_exam_types()
        for exam_ref in calculated:
            sources[exam_ref] = set(creatinine)

    return sources


def available_exams() -> set[str]:
    """The references of the catalog the schema has results for (a rule on
    another would never fire)"""
    return {
        exam_ref
        for exam_ref, exam_types in exam_sources(set(EXAM_TRIGGER_EXAMS)).items()
        if exam_types
    }


def _refs_by_type(sources: dict[str, set[str]]) -> dict[str, set[str]]:
    """tpexame -> the references reading it (the creatinine reads for both
    CKDs)"""
    refs: dict[str, set[str]] = {}
    for exam_ref, exam_types in sources.items():
        for exam_type in exam_types:
            refs.setdefault(exam_type, set()).add(exam_ref)
    return refs


def calc_value(
    exam_ref: str, raw_value: float | None, patient: PatientData
) -> float | None:
    """The value a rule compares: the result, or the CKD calculated from the
    creatinine (None when it can't be calculated)"""
    if raw_value is None:
        return None

    if exam_ref not in CALCULATED_EXAMS:
        # the results are kept as real: 1.1 reads 1.10000002
        return round(float(raw_value), 4)

    return _calculated(exam_ref, raw_value, patient).get("value")


def _calculated(exam_ref: str, raw_value: float, patient: PatientData) -> dict:
    """The CKD calculated from a creatinine: value (None when it can't be
    calculated: no birthdate, not an adult) and unit"""
    if patient.birthdate is None:
        return {}
    if dateutils.data2age(patient.birthdate.isoformat()) < CALCULATED_MIN_AGE:
        return {}

    creatinine = float(raw_value)
    if exam_ref == "ckd21":
        calculated = examutils.ckd_calc_21(
            creatinine, patient.birthdate, patient.gender
        )
    else:
        calculated = examutils.ckd_calc(
            creatinine,
            patient.birthdate,
            patient.gender,
            patient.skin_color,
            patient.height,
            patient.weight,
        )

    value = calculated.get("value")
    return {"value": float(value) if value else None, "unit": calculated.get("unit")}


def _result_entry(
    result: ExamResult, exam_ref: str, patient: PatientData
) -> dict | None:
    """A result as an evaluation or a pending reason keeps it (a calculated
    exam also keeps the creatinine it came from)"""
    value = calc_value(exam_ref, result.raw_value, patient)
    if value is None:
        return None

    entry = {
        "examType": result.exam_type,
        "date": dateutils.to_iso(result.date),
        "value": value,
        "unit": result.unit,
    }
    if exam_ref in CALCULATED_EXAMS:
        entry["unit"] = _calculated(exam_ref, result.raw_value, patient).get("unit")
        entry["rawValue"] = round(float(result.raw_value), 4)
        entry["rawUnit"] = result.unit
    return entry


def _latest_archived(
    schema: str, id_patient: int, sources: dict[str, set[str]], until: datetime
) -> dict[str, ExamResult]:
    """The latest archived result (DynamoDB) of each reference, up to `until`.
    A failure leaves the baseline out: the review is still saved"""
    try:
        items = exams_repository.get_exams_by_patient_from_dynamodb(
            schema=schema, id_patient=id_patient
        )
    except Exception as e:  # noqa: BLE001 - the baseline is optional
        logger.backend_logger.error(
            f"Exam trigger baseline from DynamoDB failed (schema {schema}): {e}"
        )
        return {}

    refs_by_type = _refs_by_type(sources)
    latest: dict[str, ExamResult] = {}
    for item in items:
        exam_type = (item.get("tpexame") or "").lower()
        exam_refs = refs_by_type.get(exam_type)
        if not exam_refs or item.get("resultado") is None:
            continue

        date = item.get("dtexame")
        try:
            date = parser.parse(date) if isinstance(date, str) else date
        except (ValueError, OverflowError):
            continue
        if not isinstance(date, datetime):
            continue
        # the exams are kept in local time, as the rule compares them
        date = date.replace(tzinfo=None)
        if date > until:
            continue

        result = ExamResult(
            exam_type=exam_type,
            date=date,
            raw_value=float(item.get("resultado")),
            unit=item.get("unidade"),
        )
        for exam_ref in exam_refs:
            current = latest.get(exam_ref)
            if current is None or date > current.date:
                latest[exam_ref] = result

    return latest


def snapshot(
    rules: list[ExamTriggerRule],
    admission_number: int,
    schema: str,
    now: datetime,
) -> list[dict]:
    """The rules turned on in an evaluation, each with its baseline: the latest
    result of its exam up to now (None when there is none)"""
    if not rules:
        return []

    patient = patient_repository.get_patient_by_admission(admission_number)
    patient_data = PatientData.of(patient)
    sources = exam_sources({rule.examRef for rule in rules})

    latest: dict[str, ExamResult] = {}
    if patient is not None:
        refs_by_type = _refs_by_type(sources)
        for row in exams_repository.get_patient_results(
            id_patient=patient.idPatient, exam_types=set(refs_by_type), until=now
        ):
            exam_type = row.typeExam.lower()
            for exam_ref in refs_by_type[exam_type]:
                latest[exam_ref] = ExamResult(
                    exam_type=exam_type,
                    date=row.date,
                    raw_value=row.value,
                    unit=row.unit,
                )

        missing = {
            exam_ref: exam_types
            for exam_ref, exam_types in sources.items()
            if exam_types and exam_ref not in latest
        }
        if missing:
            latest.update(
                _latest_archived(
                    schema=schema,
                    id_patient=patient.idPatient,
                    sources=missing,
                    until=now,
                )
            )

    entries = []
    for rule in rules:
        baseline = latest.get(rule.examRef)
        entries.append(
            {
                "type": TRIGGER_TYPE_EXAM,
                **rule.model_dump(exclude={"enabledByDefault"}),
                "baseline": (
                    _result_entry(baseline, rule.examRef, patient_data)
                    if baseline
                    else None
                ),
            }
        )

    return entries


# --- the rule ---


def evaluation_exam_triggers(evaluation: AntimicrobialEvaluation) -> list[dict]:
    """The exam triggers among an evaluation's triggers (gatilhos keeps the
    pending types as ints and the triggers with parameters as objects)"""
    return [
        trigger
        for trigger in evaluation.triggers or []
        if isinstance(trigger, dict) and trigger.get("type") == TRIGGER_TYPE_EXAM
    ]


def watched_since(evaluation: AntimicrobialEvaluation, trigger: dict) -> datetime:
    """Results after this one count: the baseline's, or when the evaluation
    was made without one"""
    baseline = trigger.get("baseline")
    if baseline and baseline.get("date"):
        return datetime.fromisoformat(baseline["date"])

    return evaluation.created_at


def _cached_result(exam_type: str, cached: dict | None) -> ExamResult | None:
    """A result of the exams cache (None without a value or a valid date)"""
    if not cached or cached.get("value") is None or not cached.get("date"):
        return None

    try:
        # the exams are kept in local time, as the rule compares them
        date = datetime.fromisoformat(cached["date"]).replace(tzinfo=None)
        value = float(cached["value"])
    except (TypeError, ValueError):
        return None

    return ExamResult(
        exam_type=exam_type, date=date, raw_value=value, unit=cached.get("unit")
    )


# load_results reads the patient itself unless given one (None included)
_READ_PATIENT = object()


def load_results(
    admission_number: int,
    schema: str,
    evaluations: list[AntimicrobialEvaluation],
    patient=_READ_PATIENT,
) -> ExamResults | None:
    """The results the exam triggers of these evaluations watch, from the
    exams cache: the latest of each reference, among the exams mapped to it
    (None when none watches an exam).
    The admission's patient record is read unless given (None: it has none)"""
    watching = [
        (evaluation, trigger)
        for evaluation in evaluations
        for trigger in evaluation_exam_triggers(evaluation)
    ]
    if not watching:
        return None

    if patient is _READ_PATIENT:
        patient = patient_repository.get_patient_by_admission(admission_number)
    if patient is None:
        return ExamResults()

    refs_by_type = _refs_by_type(
        exam_sources({trigger["examRef"] for _, trigger in watching})
    )
    cached = exams_repository.get_cached_exams(
        schema=schema, id_patient=patient.idPatient
    )

    # a reference may read several exams of the schema: the latest wins, as in
    # the prescription view (a tie keeps the first, in tpexame order)
    latest: dict[str, ExamResult] = {}
    for exam_type in sorted(refs_by_type):
        result = _cached_result(exam_type, cached.get(exam_type))
        if result is None:
            continue
        for exam_ref in refs_by_type[exam_type]:
            current = latest.get(exam_ref)
            if current is None or result.date > current.date:
                latest[exam_ref] = result

    return ExamResults(
        by_ref={exam_ref: [result] for exam_ref, result in latest.items()},
        patient=PatientData.of(patient),
    )


# the conditions of a rule, by the suffix of their key (valueAbove,
# variationAtLeast...)
_COMPARISONS = (
    ("Above", lambda compared, limit: compared > limit),
    ("AtLeast", lambda compared, limit: compared >= limit),
    ("Below", lambda compared, limit: compared < limit),
    ("AtMost", lambda compared, limit: compared <= limit),
)


def _meets(trigger: dict, value: float, baseline_value: float | None) -> dict | None:
    """Whether a value meets every condition of a rule; the variation from the
    baseline (percent) when it does"""
    variation = None
    if baseline_value:
        variation = round((value - baseline_value) / baseline_value * 100, 2)

    for subject, compared in (("value", value), ("variation", variation)):
        for suffix, met in _COMPARISONS:
            limit = trigger.get(subject + suffix)
            if limit is None:
                continue
            if compared is None or not met(compared, limit):
                return None

    return {"variation": variation}


def exam_matches(
    evaluation: AntimicrobialEvaluation,
    course: Course,
    results: ExamResults | None,
    now: datetime,
) -> list[dict]:
    """The exam trigger rules of an evaluation a result met, each with the
    first result that met it"""
    triggers = evaluation_exam_triggers(evaluation)
    if results is None or not triggers:
        return []

    matches = []
    for trigger in triggers:
        since = watched_since(evaluation, trigger)
        baseline = trigger.get("baseline") or {}
        from_day = trigger.get("fromCourseDay")

        for result in results.results(trigger["examRef"]):
            if result.date <= since or result.date > now:
                continue
            if from_day and started_days(course.start, result.date) < from_day:
                continue

            entry = _result_entry(result, trigger["examRef"], results.patient)
            if entry is None:
                continue

            met = _meets(trigger, entry["value"], baseline.get("value"))
            if met is None:
                continue

            matches.append(
                {
                    "id": trigger["id"],
                    "name": trigger["name"],
                    "examRef": trigger["examRef"],
                    "result": entry,
                    "baseline": trigger.get("baseline"),
                    "variation": met["variation"],
                }
            )
            break

    return matches
