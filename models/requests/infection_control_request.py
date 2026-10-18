from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from pydantic import AfterValidator, BaseModel, Field

# dates are stored as naive local (hospital) time
LOCAL_TZ = ZoneInfo("America/Sao_Paulo")


def _to_local_naive(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(LOCAL_TZ).replace(tzinfo=None)
    return value


LocalDatetime = Annotated[datetime, AfterValidator(_to_local_naive)]


class AntimicrobialEvaluationRequest(BaseModel):
    """Conformity of one running antimicrobial, judged in a review"""

    idDrug: int
    conforming: bool
    notes: str | None = None
    # intervention reasons of a non-conformity (flagged for infection control)
    interventionReasons: list[int] = []
    # the drug recommended instead, for reasons related to another drug
    substituteDrug: int | None = None
    # record an intervention on the drug with the non-conformity reasons
    createIntervention: bool = False
    # the evaluation applies from this date, between the course start and now;
    # empty means from the review
    validFrom: LocalDatetime | None = None
    # the evaluation holds until this date
    validUntil: LocalDatetime
    # optional reasons that send the patient back to pending (pending types)
    triggers: list[int] = []


class InfectionControlReviewRequest(BaseModel):
    """A review of the patient: drugs evaluated and the next review date"""

    admissionNumber: int
    notes: str | None = None
    nextReviewDate: LocalDatetime | None = None
    evaluations: list[AntimicrobialEvaluationRequest] = []


class InfectionControlListRequest(BaseModel):
    """Followed admissions, filtered by status and by the worklist filters"""

    status: list[int] = []
    # department of the latest prescription of the admission
    idDepartment: list[int] = []
    # admissions with an open pending reason of any of these types
    pendingTypes: list[int] = []
    admissionNumbers: list[int] = []
    # admissions whose scheduled review date has passed
    overdueReview: bool = False
    # the filters below read what the rule last saw running (indicadores)
    # admissions running any of these antimicrobials
    idDrug: list[int] = []
    # admissions running an antimicrobial of any of these substances
    idSubstance: list[int] = []
    # admissions running an antimicrobial of any of these AWaRe levels
    awareLevels: list[int] = []
    # admissions with an antimicrobial running for at least this many days (D1
    # is the first 24 hours, as in the timeline)
    minTreatmentDays: int | None = Field(default=None, ge=1)
    # admissions with an evaluation in force judged non conforming
    nonConforming: bool = False
    limit: int = Field(default=100, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


class InfectionControlBackfillRequest(BaseModel):
    """One batch of the backfill, resumed after the last admission processed"""

    after: int = 0
    limit: int = Field(default=50, ge=1, le=200)
