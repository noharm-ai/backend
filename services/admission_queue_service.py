"""Service: admission queues (fila_atendimento)

A flow that redoes something per admission when the admission's data changes
(e.g. the infection control rule) doesn't have to go through every admission
on a timer: the producers (prescalc) queue the admissions that changed, and the
flow's job (in backend-private) runs only on the queued ones.

Each consumer has its own queue (tp_fila, AdmissionQueueEnum), one row per
admission:
* a producer calls notify, which queues the admission for every consumer whose
  feature is on and whose condition the admission meets, in the producer's
  transaction (the queue row commits with the change that queued it);
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

from sqlalchemy.sql.elements import ColumnElement

from models.enums import AdmissionQueueEnum, AdmissionQueueReasonEnum, FeatureEnum
from models.main import db
from repository import admission_queue_repository
from repository.infection_control import infection_control_repository
from services import feature_service
from utils import db_utils, logger

# a producer never waits long for a queue row (another producer queuing the
# same admission, or a consumer dequeuing it)
LOCK_TIMEOUT_MS = 5000


@dataclass(frozen=True)
class QueueConsumer:
    """A flow that runs on the admissions queued for it"""

    queue: AdmissionQueueEnum
    # queued only in the schemas with this feature on (None: every schema)
    feature: FeatureEnum | None
    # queued only when this condition on the admission holds (None: always)
    condition: Callable[[int], ColumnElement[bool]] | None


CONSUMERS = (
    # the light infection control run applies the rule to the followed
    # admissions that changed
    QueueConsumer(
        queue=AdmissionQueueEnum.INFECTION_CONTROL,
        feature=FeatureEnum.INFECTION_CONTROL,
        condition=infection_control_repository.followed_condition,
    ),
)


def notify(schema: str, admission_number: int, reason: AdmissionQueueReasonEnum):
    """Queue the admission for every consumer that wants it.

    Each consumer in a savepoint of its own, and never raises: the producer's
    work is the core product and must be saved even if a queue fails (e.g. a
    schema without fila_atendimento yet), and one consumer's failure must not
    keep the admission from the others.
    """
    # flush the producer's own changes first: begin_nested() would flush them
    # inside the try below, and their errors must surface as the producer's
    db.session.flush()
    now = datetime.now()

    for consumer in CONSUMERS:
        try:
            with (
                db.session.begin_nested(),
                db_utils.lock_timeout(LOCK_TIMEOUT_MS),
            ):
                if consumer.feature and not feature_service.has_feature(
                    consumer.feature
                ):
                    continue

                admission_queue_repository.enqueue(
                    queue=consumer.queue,
                    admission_number=admission_number,
                    reason=reason,
                    now=now,
                    only_if=(
                        consumer.condition(admission_number)
                        if consumer.condition
                        else None
                    ),
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
                        "admission_number": admission_number,
                        "queue": consumer.queue.name,
                        "reason": reason.value,
                    }
                )
            )
