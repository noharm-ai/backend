"""Service: the antimicrobials whose courses need no infection control review

Not every antimicrobial needs the infectologist's review: each schema keeps a
list of exceptions (models/infection_control_config.py, ReviewExceptionsData)
in its memoria (kind MemoryEnum.INFECTION_CONTROL_REVIEW_EXCEPTIONS, an admin
kind: only this service writes it, and only for WRITE_INFECTION_CONTROL).

A substance covers every drug of it; a drug is the fallback for the drugs
without a substance. An exempt course is still antimicrobial therapy (the
timeline, the summary, DOT/LOT), but the rule opens no reason for it and the
report leaves it out of the review indicators (reviewRequired false on the
summary course). The rule reads the list on every run (load), so a change
reaches an admission on its next run: saving queues the followed admissions
running a drug the change concerns for the light run.
"""

from dataclasses import dataclass, field
from datetime import datetime

from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from models.appendix import Memory
from models.enums import (
    AdmissionQueueEnum,
    AdmissionQueueReasonEnum,
    FeatureEnum,
    MemoryEnum,
)
from models.infection_control_config import (
    ReviewExceptionsData,
    parse_review_exceptions,
)
from models.main import User, db
from models.requests.infection_control_request import ReviewExceptionsSaveRequest
from repository import admission_queue_repository
from repository.infection_control import (
    infection_control_repository,
    review_exception_repository,
)
from services import feature_service
from utils import dateutils, status

# letters typed before the antimicrobials are searched
MIN_SEARCH = 3


@dataclass(frozen=True)
class ReviewExceptions:
    """The schema's review exceptions, as the rule reads them"""

    substances: frozenset[int] = field(default_factory=frozenset)
    drugs: frozenset[int] = field(default_factory=frozenset)

    def is_exempt(self, id_drug: int | None, id_substance: int | None) -> bool:
        """Whether a drug (with its substance, if it has one) needs no review"""
        return (id_substance is not None and id_substance in self.substances) or (
            id_drug is not None and id_drug in self.drugs
        )


# nothing exempt: every antimicrobial is reviewed
NO_EXCEPTIONS = ReviewExceptions()


def _as_exceptions(data: ReviewExceptionsData) -> ReviewExceptions:
    """The kept list as the rule reads it"""
    return ReviewExceptions(
        substances=frozenset(data.substances), drugs=frozenset(data.drugs)
    )


def load() -> ReviewExceptions:
    """The schema's review exceptions (none without a record). The functions
    here carry no permission check: the rule runs inside callers that have
    one"""
    record = review_exception_repository.get_record()
    return _as_exceptions(parse_review_exceptions(record.value if record else None))


def _check_feature():
    """The infection control must be on for the schema"""
    if not feature_service.has_feature(FeatureEnum.INFECTION_CONTROL):
        raise ValidationError(
            "Controle de infecção não está habilitado",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )


def _view(data: ReviewExceptionsData, record: Memory | None) -> dict:
    """The list with the names of each substance and drug"""
    substance_names = review_exception_repository.get_substance_names(
        set(data.substances)
    )
    drug_names = infection_control_repository.get_drug_names(set(data.drugs))

    return {
        "substances": sorted(
            ({"id": str(i), "name": substance_names.get(i)} for i in data.substances),
            key=lambda item: (item["name"] or "", item["id"]),
        ),
        "drugs": sorted(
            ({"id": str(i), "name": drug_names.get(i)} for i in data.drugs),
            key=lambda item: (item["name"] or "", item["id"]),
        ),
        "updatedAt": dateutils.to_iso(record.update) if record else None,
    }


@has_permission(Permission.READ_INFECTION_CONTROL)
def get_review_exceptions():
    """The antimicrobials whose courses need no review"""
    _check_feature()

    record = review_exception_repository.get_record()
    return _view(parse_review_exceptions(record.value if record else None), record)


@has_permission(Permission.READ_INFECTION_CONTROL)
def search_options(term: str | None):
    """What the list can hold, by name: the substances of the antimicrobial
    drugs and the antimicrobial drugs without a substance"""
    _check_feature()

    term = (term or "").strip()
    if len(term) < MIN_SEARCH:
        return {"substances": [], "drugs": []}

    return {
        "substances": [
            {"id": str(i), "name": name}
            for i, name in review_exception_repository.search_substances(term=term)
        ],
        "drugs": [
            {"id": str(i), "name": name}
            for i, name in review_exception_repository.search_drugs_without_substance(
                term=term
            )
        ],
    }


def _validate(request_data: ReviewExceptionsSaveRequest, current: ReviewExceptionsData):
    """Only substances of antimicrobials and antimicrobial drugs may be added
    (one kept from before stays, even if no longer offered, so the others can
    still be saved)"""
    new_substances = set(request_data.substances) - set(current.substances)
    if new_substances:
        found = {
            i
            for i, _ in review_exception_repository.search_substances(
                id_substances=new_substances, limit=len(new_substances)
            )
        }
        if new_substances - found:
            raise ValidationError(
                "Substância não é de um antimicrobiano",
                "errors.invalidRecord",
                status.HTTP_400_BAD_REQUEST,
            )

    new_drugs = set(request_data.drugs) - set(current.drugs)
    if new_drugs:
        found = {
            i
            for i, _ in infection_control_repository.search_antimicrobials(
                id_drugs=new_drugs, limit=len(new_drugs)
            )
        }
        if new_drugs - found:
            raise ValidationError(
                "Medicamento não é um antimicrobiano",
                "errors.invalidRecord",
                status.HTTP_400_BAD_REQUEST,
            )


@has_permission(Permission.WRITE_INFECTION_CONTROL)
def save_review_exceptions(
    request_data: ReviewExceptionsSaveRequest, user_context: User
):
    """Replace the antimicrobials whose courses need no review, and queue the
    followed admissions running a drug the change concerns, so the light run
    opens or settles their reasons (the full run would, later)"""
    _check_feature()

    record = review_exception_repository.get_record()
    current = parse_review_exceptions(record.value if record else None)
    _validate(request_data=request_data, current=current)

    saved = ReviewExceptionsData(
        substances=sorted(set(request_data.substances)),
        drugs=sorted(set(request_data.drugs)),
    )
    now = datetime.now()
    if record is None:
        record = Memory()
        record.kind = MemoryEnum.INFECTION_CONTROL_REVIEW_EXCEPTIONS.value
        db.session.add(record)
    record.value = saved.model_dump()
    record.update = now
    record.user = user_context.id
    db.session.flush()

    for admission_number in review_exception_repository.get_followed_running(
        id_drugs=set(saved.drugs) ^ set(current.drugs),
        id_substances=set(saved.substances) ^ set(current.substances),
    ):
        admission_queue_repository.enqueue(
            queue=AdmissionQueueEnum.INFECTION_CONTROL,
            admission_number=admission_number,
            reason=AdmissionQueueReasonEnum.REVIEW_EXCEPTIONS,
            now=now,
        )

    return _view(saved, record)
