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
    # the evaluation holds until this date
    validUntil: LocalDatetime


class InfectionControlReviewRequest(BaseModel):
    """A review of the patient: drugs evaluated and the next review date"""

    admissionNumber: int
    notes: str | None = None
    nextReviewDate: LocalDatetime | None = None
    evaluations: list[AntimicrobialEvaluationRequest] = []


class InfectionControlListRequest(BaseModel):
    """Followed admissions, filtered by status"""

    status: list[int] = []
    limit: int = Field(default=100, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


class InfectionControlBackfillRequest(BaseModel):
    """One batch of the backfill, resumed after the last admission processed"""

    after: int = 0
    limit: int = Field(default=50, ge=1, le=200)
