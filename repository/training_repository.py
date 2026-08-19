"""Repository: training related operations"""

from datetime import datetime

from sqlalchemy import and_, case, func, or_

from models.main import db
from models.enums import TrainingScopeEnum
from models.appendix import (
    Training,
    TrainingItem,
    TrainingItemUser,
    TrainingSchema,
    TrainingUser,
)


def list_trainings(user_id: int, schema: str) -> list:
    """List the active training records visible to the given schema, ordered by
    position, paired with the total number of active lessons, how many of those
    the user finished, and whether the module is mandatory for that schema"""
    total_lessons = (
        db.session.query(func.count(TrainingItem.id))
        .filter(
            TrainingItem.training_id == Training.id,
            TrainingItem.active == True,
        )
        .correlate(Training)
        .scalar_subquery()
    )

    total_lessons_finished = (
        db.session.query(func.count(TrainingItemUser.training_item_id))
        .join(TrainingItem, TrainingItem.id == TrainingItemUser.training_item_id)
        .filter(
            TrainingItem.training_id == Training.id,
            TrainingItem.active == True,
            TrainingItemUser.user_id == user_id,
        )
        .correlate(Training)
        .scalar_subquery()
    )

    scope_mandatory = case(
        (Training.scope == TrainingScopeEnum.SCHEMAS.value, TrainingSchema.mandatory),
        else_=Training.mandatory,
    )

    return (
        db.session.query(
            Training, total_lessons, total_lessons_finished, scope_mandatory
        )
        .outerjoin(
            TrainingSchema,
            and_(
                TrainingSchema.training_id == Training.id,
                TrainingSchema.schema_name == schema,
            ),
        )
        .filter(Training.active == True)
        # fail closed: a scope=schemas module with no row for this schema drops
        # out here, which is also why scope_mandatory never sees a NULL join row
        .filter(
            or_(
                Training.scope == TrainingScopeEnum.GLOBAL.value,
                TrainingSchema.schema_name != None,
            )
        )
        .order_by(Training.position)
        .all()
    )


def list_training_items(training_id: int, user_id: int) -> list:
    """List all active items of a training record ordered by position, paired
    with whether the given user has finished each item"""
    finished = case((TrainingItemUser.user_id.isnot(None), True), else_=False)

    return (
        db.session.query(TrainingItem, finished)
        .outerjoin(
            TrainingItemUser,
            and_(
                TrainingItemUser.training_item_id == TrainingItem.id,
                TrainingItemUser.user_id == user_id,
            ),
        )
        .filter(
            TrainingItem.training_id == training_id,
            TrainingItem.active == True,
        )
        .order_by(TrainingItem.position)
        .all()
    )


def finish_training_item(
    training_item_id: int, user_id: int, duration_seconds: int = None
) -> TrainingItemUser:
    """Create or update the record marking a training item as finished by a user"""
    record = TrainingItemUser.query.get((training_item_id, user_id))

    if record is None:
        record = TrainingItemUser()
        record.training_item_id = training_item_id
        record.user_id = user_id
        record.created_at = datetime.today()
        db.session.add(record)
    else:
        record.updated_at = datetime.today()

    record.duration_seconds = duration_seconds

    return record


def get_training_id_for_item(training_item_id: int) -> int:
    """Return the training id that owns the given training item"""
    return (
        db.session.query(TrainingItem.training_id)
        .filter(TrainingItem.id == training_item_id)
        .scalar()
    )


def is_training_finished(training_id: int, user_id: int) -> bool:
    """Check whether the user has finished every active item of a training"""
    total_items = (
        db.session.query(func.count(TrainingItem.id))
        .filter(
            TrainingItem.training_id == training_id,
            TrainingItem.active == True,
        )
        .scalar()
    )

    if not total_items:
        return False

    finished_items = (
        db.session.query(func.count(TrainingItemUser.training_item_id))
        .join(TrainingItem, TrainingItem.id == TrainingItemUser.training_item_id)
        .filter(
            TrainingItem.training_id == training_id,
            TrainingItem.active == True,
            TrainingItemUser.user_id == user_id,
        )
        .scalar()
    )

    return finished_items == total_items


def finish_training(training_id: int, user_id: int) -> bool:
    """Create the record marking a training module as finished by a user, if
    not already present. Returns True the first time it's created for this user"""
    record = TrainingUser.query.get((training_id, user_id))

    if record is not None:
        return False

    record = TrainingUser()
    record.training_id = training_id
    record.user_id = user_id
    record.created_at = datetime.today()
    db.session.add(record)

    return True
