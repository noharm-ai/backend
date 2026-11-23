"""Exam trigger rules of the infection control, defined by the users and kept
in the schema's memoria (kind MemoryEnum.INFECTION_CONTROL_EXAM_TRIGGERS, one
record holding the list; GET/PUT /infection-control/exam-triggers).

An exam trigger rule sends the patient back to pending (a reason of the drug,
InfectionControlPendingTypeEnum.EXAM_RESULT) when an exam result meets all the
conditions it sets. The reviewer turns the rules on per drug evaluation; the
rule is copied on the evaluation with its baseline, so editing or deleting it
here never changes what an evaluation already watches (see
services/infection_control/exam_trigger_service.py).
"""

from pydantic import BaseModel, ConfigDict, Field, model_validator

from utils import logger

# the exams a rule can watch are the active global exams flagged for it
# (public.exame.gatilho_controle_infeccao), by their reference
# (segmentoexame.tpexame_ref, normalized in every schema): see
# exams_repository.get_infection_control_trigger_exams. Checked when the rules
# are saved, not here: a kept rule whose exam is no longer offered stays, shown
# as unavailable.
# not results of their own: calculated from the creatinine (the schema's exam
# whose abbreviation is "creatinina", as the exams screen finds it) with the
# patient's data, only for adults, as the exams screen does
CALCULATED_EXAMS = frozenset({"ckd", "ckd21"})

# the conditions a rule may set; all that are set must hold on one result
VALUE_CONDITIONS = (
    "valueAbove",
    "valueAtLeast",
    "valueBelow",
    "valueAtMost",
)
VARIATION_CONDITIONS = (
    "variationAbove",
    "variationAtLeast",
    "variationBelow",
    "variationAtMost",
)
EXAM_TRIGGER_CONDITIONS = VALUE_CONDITIONS + VARIATION_CONDITIONS


class ExamTriggerRuleData(BaseModel):
    """A condition on the results of one exam of the catalog, as the users
    write it (the id is kept by the system)"""

    model_config = ConfigDict(extra="ignore")

    # shown to the reviewer and in the pending reason
    name: str = Field(min_length=1, max_length=100)
    # the exam reference (a flagged public.exame.tpexame)
    examRef: str
    # the value is over (>) / at least (>=) / under (<) / at most (<=) these
    valueAbove: float | None = None
    valueAtLeast: float | None = None
    valueBelow: float | None = None
    valueAtMost: float | None = None
    # the variation from the baseline, in percent, compared the same way
    # (signed: variationAbove 30 means a rise of more than 30%, variationBelow
    # -25 a fall of more than 25%); not met without a baseline (unless
    # variationOptional), and from a zero baseline any rise is unbounded (a
    # rise is met, a fall is not)
    variationAbove: float | None = None
    variationAtLeast: float | None = None
    variationBelow: float | None = None
    variationAtMost: float | None = None
    # without a baseline (no result at review time), the variation conditions
    # are skipped and the value conditions decide alone, instead of the rule
    # never firing ("> 0.5 and, when there was a previous result, a fall of
    # less than 50%"); needs a value condition, or it would fire on any result
    variationOptional: bool = False
    # only results from this treatment day of the course on (D1 is the first
    # 24 hours, as the timeline counts; 4 means after D3)
    fromCourseDay: int | None = Field(default=None, ge=1)
    # turned on in a new evaluation of the drug
    enabledByDefault: bool = False

    @model_validator(mode="after")
    def _valid(self):
        """A name, an exam and a condition (a rule without one would fire on
        any result)"""
        self.name = self.name.strip()
        self.examRef = self.examRef.strip().lower()
        if not self.name:
            raise ValueError("an exam trigger rule needs a name")
        if all(getattr(self, c) is None for c in EXAM_TRIGGER_CONDITIONS):
            raise ValueError("an exam trigger rule needs a condition")
        if self.variationOptional:
            if all(getattr(self, c) is None for c in VARIATION_CONDITIONS):
                # nothing to skip
                self.variationOptional = False
            elif all(getattr(self, c) is None for c in VALUE_CONDITIONS):
                raise ValueError(
                    "an exam trigger rule with an optional variation needs a "
                    "value condition"
                )
        return self


class ExamTriggerRuleInput(ExamTriggerRuleData):
    """A rule sent by the users: no id when it is new"""

    id: str | None = None


class ExamTriggerRule(ExamTriggerRuleData):
    """A rule as kept: its id is what the review sends and the evaluation
    keeps"""

    id: str = Field(min_length=1)


def parse_exam_trigger_rules(value) -> list[ExamTriggerRule]:
    """The rules kept in the memoria record. An invalid rule (or one repeating
    an id) is left out on its own, so it never takes the others down"""
    if not isinstance(value, list):
        return []

    rules = []
    ids = set()
    for item in value:
        try:
            rule = ExamTriggerRule.model_validate(item)
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.backend_logger.error("exam trigger rule ignored: %s", e)
            continue

        if rule.id in ids:
            logger.backend_logger.error(
                "exam trigger rule %s repeated, ignored", rule.id
            )
            continue

        ids.add(rule.id)
        rules.append(rule)

    return rules


# --- review exceptions ---

# bounds what one schema can keep: far more than any formulary needs
MAX_REVIEW_EXCEPTIONS = 500


class ReviewExceptionsData(BaseModel):
    """The antimicrobials of a schema whose courses need no review, kept in the
    schema's memoria (kind MemoryEnum.INFECTION_CONTROL_REVIEW_EXCEPTIONS, one
    record; GET/PUT /infection-control/review-exceptions).

    A substance (public.substancia.sctid) covers every drug of it; a drug
    (medicamento.fkmedicamento) is the fallback for the drugs without a
    substance. A course is exempt when its drug or its substance is listed:
    it still counts as antimicrobial therapy (timeline, DOT/LOT), but opens no
    pending reason and is left out of the review indicators. Empty (no record)
    reviews every antimicrobial, as before the list existed.
    """

    model_config = ConfigDict(extra="ignore")

    substances: list[int] = Field(default=[], max_length=MAX_REVIEW_EXCEPTIONS)
    drugs: list[int] = Field(default=[], max_length=MAX_REVIEW_EXCEPTIONS)


def parse_review_exceptions(value) -> ReviewExceptionsData:
    """The review exceptions kept in memoria; a record that can't be read
    reviews every antimicrobial (as with no record), and is logged"""
    if value is None:
        return ReviewExceptionsData()

    try:
        return ReviewExceptionsData.model_validate(value)
    except Exception:  # noqa: BLE001 - never break the rule on a bad record
        logger.backend_logger.warning("invalid infection control review exceptions")
        return ReviewExceptionsData()


# the exams the antimicrobial timeline opens with when the schema never chose
# them, by reference (segmentoexame.tpexame_ref): CRP, CKD-EPI (or CKD-EPI
# 2021, where configured instead) and leukocytes
DEFAULT_TIMELINE_EXAMS = ["pcru", "ckd", "ckd21", "h_conleuc"]
MAX_TIMELINE_EXAMS = 10


def normalize_exam_refs(refs: list[str]) -> list[str]:
    """References in lower case, without blanks or repeats, in their order"""
    normalized = []
    for ref in refs:
        ref = (ref or "").strip().lower()
        if ref and ref not in normalized:
            normalized.append(ref)
    return normalized


class TimelineExamsData(BaseModel):
    """The exams the antimicrobial timeline of an admission opens with, kept in
    the schema's memoria (kind MemoryEnum.INFECTION_CONTROL_TIMELINE_EXAMS,
    one record; GET/PUT /infection-control/timeline-exams).

    Each is a reference (segmentoexame.tpexame_ref, the same in every schema),
    plotted in this order when the patient has results of it; the others are
    added from the timeline. Without a record, DEFAULT_TIMELINE_EXAMS.
    """

    model_config = ConfigDict(extra="ignore")

    exams: list[str] = Field(default=[], max_length=MAX_TIMELINE_EXAMS)

    @model_validator(mode="after")
    def _normalize(self):
        """References in lower case, each once"""
        self.exams = normalize_exam_refs(self.exams)
        return self


def parse_timeline_exams(value) -> TimelineExamsData | None:
    """The timeline exams kept in memoria; None without a record or with one
    that can't be read (the default exams then, logged)"""
    if value is None:
        return None

    try:
        return TimelineExamsData.model_validate(value)
    except Exception:  # noqa: BLE001 - the timeline opens with the default
        logger.backend_logger.warning("invalid infection control timeline exams")
        return None
