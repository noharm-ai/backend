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

# the exams a rule can watch, by their reference (segmentoexame.tpexame_ref,
# normalized in every schema), with the name the users see
EXAM_TRIGGER_EXAMS = {
    "pcru": "PCR",
    "temp": "Temperatura",
    "ckd": "CKD",
    "ckd21": "CKD21",
    "h_conleuc": "Leucócitos Absoluto",
    "procalcitonina_adult": "Procalcitonina",
    "van": "Vancocinemia",
}
# not results of their own: calculated from the creatinine (the schema's exam
# whose abbreviation is "creatinina", as the exams screen finds it) with the
# patient's data, only for adults, as the exams screen does
CALCULATED_EXAMS = frozenset({"ckd", "ckd21"})

# the conditions a rule may set; all that are set must hold on one result
EXAM_TRIGGER_CONDITIONS = (
    "valueAbove",
    "valueAtLeast",
    "valueBelow",
    "valueAtMost",
    "variationAbove",
    "variationAtLeast",
    "variationBelow",
    "variationAtMost",
)


class ExamTriggerRuleData(BaseModel):
    """A condition on the results of one exam of the catalog, as the users
    write it (the id is kept by the system)"""

    model_config = ConfigDict(extra="ignore")

    # shown to the reviewer and in the pending reason
    name: str = Field(min_length=1, max_length=100)
    # the exam reference (EXAM_TRIGGER_EXAMS)
    examRef: str
    # the value is over (>) / at least (>=) / under (<) / at most (<=) these
    valueAbove: float | None = None
    valueAtLeast: float | None = None
    valueBelow: float | None = None
    valueAtMost: float | None = None
    # the variation from the baseline, in percent, compared the same way
    # (signed: variationAbove 30 means a rise of more than 30%, variationBelow
    # -25 a fall of more than 25%); not met without a baseline, and from a
    # zero baseline any rise is unbounded (a rise is met, a fall is not)
    variationAbove: float | None = None
    variationAtLeast: float | None = None
    variationBelow: float | None = None
    variationAtMost: float | None = None
    # only results from this treatment day of the course on (D1 is the first
    # 24 hours, as the timeline counts; 4 means after D3)
    fromCourseDay: int | None = Field(default=None, ge=1)
    # turned on in a new evaluation of the drug
    enabledByDefault: bool = False

    @model_validator(mode="after")
    def _valid(self):
        """A name, an exam of the catalog and a condition (a rule without one
        would fire on any result)"""
        self.name = self.name.strip()
        self.examRef = self.examRef.strip().lower()
        if not self.name:
            raise ValueError("an exam trigger rule needs a name")
        if self.examRef not in EXAM_TRIGGER_EXAMS:
            raise ValueError(f"exam not available for a trigger: {self.examRef}")
        if all(getattr(self, c) is None for c in EXAM_TRIGGER_CONDITIONS):
            raise ValueError("an exam trigger rule needs a condition")
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
