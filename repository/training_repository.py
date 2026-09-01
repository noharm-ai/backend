"""Repository: training related operations"""

from datetime import datetime

from sqlalchemy import and_, case, func, or_

from models.main import User, db
from models.enums import TrainingScopeEnum
from models.appendix import (
    Training,
    TrainingItem,
    TrainingItemUser,
    TrainingSchema,
    TrainingUser,
)
from exception.validation_error import ValidationError
from utils import certificateutils, status


def _active_lessons_subquery():
    """Correlated count of a module's active lessons"""
    return (
        db.session.query(func.count(TrainingItem.id))
        .filter(
            TrainingItem.training_id == Training.id,
            TrainingItem.active == True,
        )
        .correlate(Training)
        .scalar_subquery()
    )


def _scope_mandatory_case():
    """The mandatory flag that applies to a module: for scope=schemas it lives
    on the joined TrainingSchema row, for scope=global on the module itself.

    Only valid on a query built through _visible_to_schema(), which is what
    guarantees the join row exists whenever it is consulted"""
    return case(
        (Training.scope == TrainingScopeEnum.SCHEMAS.value, TrainingSchema.mandatory),
        else_=Training.mandatory,
    )


def _visible_to_schema(query, schema: str):
    """Restrict a query over Training to the active modules the given schema
    sees, joining that schema's TrainingSchema row.

    The single place this rule lives: the per-user list and the manager overview
    must never disagree about which modules exist for a schema"""
    return (
        query.outerjoin(
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
    )


def list_trainings(user_id: int, schema: str) -> list:
    """List the active training records visible to the given schema, ordered by
    position, paired with the total number of active lessons, how many of those
    the user finished, whether the module is mandatory for that schema, and
    whether the user holds a completion record (certificate) for it"""
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

    # the completion record outlives lesson-count changes, so a module that
    # gained lessons after the user finished it still offers its certificate
    certificate_available = (
        db.session.query(func.count(TrainingUser.training_id))
        .filter(
            TrainingUser.training_id == Training.id,
            TrainingUser.user_id == user_id,
        )
        .correlate(Training)
        .scalar_subquery()
    )

    return (
        _visible_to_schema(
            db.session.query(
                Training,
                _active_lessons_subquery(),
                total_lessons_finished,
                _scope_mandatory_case(),
                certificate_available,
            ),
            schema=schema,
        )
        .order_by(Training.position)
        .all()
    )


def list_schema_trainings(schema: str) -> list:
    """The active modules a schema sees, ordered by position, paired with their
    active-lesson count and the mandatory flag that applies to the schema.

    The user-independent half of list_trainings: the manager overview resolves
    progress for many users at once, so it cannot use per-user subqueries"""
    return (
        _visible_to_schema(
            db.session.query(
                Training,
                _active_lessons_subquery(),
                _scope_mandatory_case(),
            ),
            schema=schema,
        )
        .order_by(Training.position)
        .all()
    )


def list_lessons_finished_by_user(training_ids: list, user_ids: list) -> list:
    """(user_id, training_id, finished lessons) for every pair with at least one
    finished lesson, counting active lessons only.

    Same filters as list_trainings' total_lessons_finished, so a manager and the
    user themselves always read the same progress. Deliberately not
    count_finished_lessons, which counts inactive lessons too because a
    certificate reports what the user did, not the module's current content"""
    if not training_ids or not user_ids:
        return []

    return (
        db.session.query(
            TrainingItemUser.user_id,
            TrainingItem.training_id,
            func.count(TrainingItemUser.training_item_id),
        )
        .join(TrainingItem, TrainingItem.id == TrainingItemUser.training_item_id)
        .filter(
            TrainingItem.training_id.in_(training_ids),
            TrainingItem.active == True,
            TrainingItemUser.user_id.in_(user_ids),
        )
        .group_by(TrainingItemUser.user_id, TrainingItem.training_id)
        .all()
    )


def list_training_completions(training_ids: list, user_ids: list) -> list:
    """(user_id, training_id, completed_at) for every completion record among
    the given modules and users"""
    if not training_ids or not user_ids:
        return []

    return (
        db.session.query(
            TrainingUser.user_id,
            TrainingUser.training_id,
            TrainingUser.created_at,
        )
        .filter(
            TrainingUser.training_id.in_(training_ids),
            TrainingUser.user_id.in_(user_ids),
        )
        .all()
    )


def list_last_activity(training_ids: list, user_ids: list) -> list:
    """(user_id, most recent lesson activity) among the given modules.

    Inactive lessons count here: the question is when the user last touched the
    training, and that happened whether or not the lesson still exists"""
    if not training_ids or not user_ids:
        return []

    last_activity = func.max(
        func.coalesce(TrainingItemUser.updated_at, TrainingItemUser.created_at)
    )

    return (
        db.session.query(TrainingItemUser.user_id, last_activity)
        .join(TrainingItem, TrainingItem.id == TrainingItemUser.training_item_id)
        .filter(
            TrainingItem.training_id.in_(training_ids),
            TrainingItemUser.user_id.in_(user_ids),
        )
        .group_by(TrainingItemUser.user_id)
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


def get_training(training_id: int) -> Training:
    """Return the training record with the given id, if any. Inactive modules
    are included on purpose: deactivating a module must not void the
    certificates its completion records already earned"""
    return db.session.query(Training).filter(Training.id == training_id).first()


def get_training_user(training_id: int, user_id: int) -> TrainingUser:
    """Return the record marking a training module as finished by a user, if any"""
    return TrainingUser.query.get((training_id, user_id))


def get_training_user_by_code(validation_code: str):
    """Completion record, its module and its holder, for a public validation
    code. Returns None when the code matches nothing.

    Inactive modules and users are deliberately not filtered, for the reason
    already documented on get_training: deactivating a module must not void the
    certificates it already issued"""
    return (
        db.session.query(TrainingUser, Training, User)
        .join(Training, Training.id == TrainingUser.training_id)
        .join(User, User.id == TrainingUser.user_id)
        .filter(TrainingUser.validation_code == validation_code)
        .first()
    )


def count_finished_lessons(training_id: int, user_id: int) -> int:
    """Number of lessons of a training module the given user finished, whether
    or not those lessons are still active: it reports what the user actually
    did, not the module's current content"""
    return (
        db.session.query(func.count(TrainingItemUser.training_item_id))
        .join(TrainingItem, TrainingItem.id == TrainingItemUser.training_item_id)
        .filter(
            TrainingItem.training_id == training_id,
            TrainingItemUser.user_id == user_id,
        )
        .scalar()
    )


def list_finished_lessons(training_id: int, user_id: int) -> list:
    """Titles of the lessons the user finished in a module, in module order.

    Same filters as count_finished_lessons, inactive lessons included: it
    reports what the user actually did, not the module's current content"""
    results = (
        db.session.query(TrainingItem.title)
        .join(TrainingItemUser, TrainingItemUser.training_item_id == TrainingItem.id)
        .filter(
            TrainingItem.training_id == training_id,
            TrainingItemUser.user_id == user_id,
        )
        .order_by(TrainingItem.position)
        .all()
    )

    return [title for (title,) in results]


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


CODE_CANDIDATES = 10


def _generate_unique_validation_code() -> str:
    """A validation code no other completion record holds.

    Ten candidates are drawn up front and checked in a single query, so the
    common case (all ten free) costs one round trip instead of one per attempt.
    At 60 bits none of them will ever be taken; the check exists so the unique
    index on codigo_validacao is a guarantee rather than a 500 some far future
    day"""
    candidates = [certificateutils.generate_code() for _ in range(CODE_CANDIDATES)]

    taken = {
        code
        for (code,) in db.session.query(TrainingUser.validation_code)
        .filter(TrainingUser.validation_code.in_(candidates))
        .all()
    }

    for code in candidates:
        if code not in taken:
            return code

    raise ValidationError(
        "Não foi possível gerar o código de validação do certificado",
        "errors.businessRules",
        status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


def finish_training(training_id: int, user_id: int) -> bool:
    """Create the record marking a training module as finished by a user, if
    not already present. Returns True the first time it's created for this user"""
    record = TrainingUser.query.get((training_id, user_id))

    if record is not None:
        return False

    record = TrainingUser()
    record.training_id = training_id
    record.user_id = user_id
    # minted here rather than on first print: the column is NOT NULL, and the
    # code belongs to the completion itself, not to the act of printing it
    record.validation_code = _generate_unique_validation_code()
    record.created_at = datetime.today()
    db.session.add(record)

    return True
