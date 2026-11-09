"""Service: admission queues (fila_atendimento)

A flow that redoes something per admission when the admission's data changes
(e.g. the infection control rule) doesn't have to go through every admission
on a timer: the producers (prescalc) queue the admissions that changed, and the
flow's job (in backend-private) runs only on the queued ones.

Each consumer has its own queue (tp_fila, AdmissionQueueEnum), one row per
admission:
* a producer calls notify with what it changed (AdmissionChange), which queues
  the admission for every consumer whose feature is on and that wants that
  change, in the producer's transaction (the queue row commits with the change
  that queued it). Each consumer keeps out the changes it has nothing to do
  for: first from the change alone (relevant, no database), then reading the
  admission if it needs to (wants);
* the consumer reads when the admission was queued (get_queued_at) before
  reading its data, and dequeues it in the same transaction as its work only
  if that did not change (dequeue): queued again meanwhile, the change may have
  come after its reads, so it stays for the next run.

To add a consumer: a value in AdmissionQueueEnum, a QueueConsumer in
CONSUMERS, its entry in this repository dequeuing as above, and the job that
lists its queue in backend-private.

notify carries no permission check: it runs inside callers that have one.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from models.enums import AdmissionQueueEnum, AdmissionQueueReasonEnum, FeatureEnum
from models.main import db
from repository import admission_queue_repository
from repository.infection_control import infection_control_repository
from services import feature_service
from services.infection_control import infection_control_status_service
from utils import db_utils, logger

# a producer never waits long for a queue row (another producer queuing the
# same admission, or a consumer dequeuing it)
LOCK_TIMEOUT_MS = 5000


@dataclass(frozen=True)
class AdmissionChange:
    """What a producer changed in an admission: each consumer's condition
    decides from it whether the admission needs the consumer"""

    admission_number: int
    reason: AdmissionQueueReasonEnum
    # antimicrobials prescribed (not suspended) in what the producer processed
    antimicrobials: tuple[
        infection_control_status_service.PrescribedAntimicrobial, ...
    ] = ()


@dataclass(frozen=True)
class QueueConsumer:
    """A flow that runs on the admissions queued for it"""

    queue: AdmissionQueueEnum
    # queued only in the schemas with this feature on (None: every schema)
    feature: FeatureEnum | None
    # whether the change can concern the consumer at all, from the change
    # alone: no database, so a change it doesn't is skipped without a query
    # (None: every change)
    relevant: Callable[[AdmissionChange], bool] | None
    # whether the admission needs the consumer for the change; it may read the
    # admission (in the consumer's savepoint) but never writes (None: always)
    wants: Callable[[AdmissionChange], bool] | None


def _infection_control_relevant(change: AdmissionChange) -> bool:
    """Only an antimicrobial can open a reason"""
    return bool(change.antimicrobials)


def _infection_control_wants(change: AdmissionChange) -> bool:
    """The admission is followed and its antimicrobials can open a reason
    (infection_control_status_service.prescalc_needs_rule)"""
    followed, features = infection_control_repository.get_followed_features(
        admission_number=change.admission_number
    )
    return followed and infection_control_status_service.prescalc_needs_rule(
        features=features, antimicrobials=list(change.antimicrobials)
    )


CONSUMERS = (
    # the light infection control run applies the rule to the followed
    # admissions whose antimicrobials can open a reason
    QueueConsumer(
        queue=AdmissionQueueEnum.INFECTION_CONTROL,
        feature=FeatureEnum.INFECTION_CONTROL,
        relevant=_infection_control_relevant,
        wants=_infection_control_wants,
    ),
)


def notify(schema: str, change: AdmissionChange):
    """Queue the admission for every consumer that wants it.

    Each consumer in a savepoint of its own, and never raises: the producer's
    work is the core product and must be saved even if a queue fails (e.g. a
    schema without fila_atendimento yet), and one consumer's failure must not
    keep the admission from the others. A change no consumer finds relevant
    runs no query at all (prescalc is a hot path).
    """
    consumers = [c for c in CONSUMERS if c.relevant is None or c.relevant(change)]
    if not consumers:
        return

    # flush the producer's own changes first: begin_nested() would flush them
    # inside the try below, and their errors must surface as the producer's
    db.session.flush()
    now = datetime.now()

    for consumer in consumers:
        try:
            with db.session.begin_nested():
                if consumer.feature and not feature_service.has_feature(
                    consumer.feature
                ):
                    continue

                if consumer.wants is not None and not consumer.wants(change):
                    continue

                with db_utils.lock_timeout(LOCK_TIMEOUT_MS):
                    admission_queue_repository.enqueue(
                        queue=consumer.queue,
                        admission_number=change.admission_number,
                        reason=change.reason,
                        now=now,
                    )
        except Exception as e:  # noqa: BLE001 - must not break the producer
            # same event as the static context's errors, which is the one monitored
            logger.backend_logger.error(
                json.dumps(
                    {
                        "event": "backend_exception",
                        "path": "admission_queue_service.notify",
                        "schema": schema,
                        "message": str(e),
                        "admission_number": change.admission_number,
                        "queue": consumer.queue.name,
                        "reason": change.reason.value,
                    }
                )
            )
