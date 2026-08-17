"""Service: training related operations"""

from repository import training_repository, user_attribute_repository
from models.enums import TrainingAudienceEnum, UserAttributeEnum
from models.main import User, db
from models.requests.training_request import TrainingItemFinishRequest
from decorators.has_permission_decorator import has_permission, Permission


def _list_user_trainings(user_id: int, schema: str) -> list:
    """Modules visible to the given schema, each flagged with whether it is
    mandatory *for this user* - the schema scope is resolved in SQL, the audience
    is applied here - and whether they already finished it.

    The single source of truth for effective mandatory-ness: nothing else may
    compute it, or the header count and the Training Central page would silently
    disagree. Not permission decorated, so it can also run during login.
    """
    # usuario has no created_at, so the onboarding attribute row is what marks a
    # user as new; absence of the row means a pre-existing user
    is_new_user = (
        user_attribute_repository.get_value(
            id_user=user_id, kind=UserAttributeEnum.ONBOARDING.value
        )
        is not None
    )

    results = training_repository.list_trainings(user_id=user_id, schema=schema)

    return [
        {
            "id": item.id,
            "page": item.page,
            "title": item.title,
            "description": item.description,
            "position": item.position,
            "mandatory": bool(scope_mandatory)
            and (item.audience == TrainingAudienceEnum.ALL.value or is_new_user),
            "totalLessons": total_lessons,
            "totalLessonsFinished": total_lessons_finished,
            "finished": total_lessons > 0
            and total_lessons_finished == total_lessons,
        }
        for item, total_lessons, total_lessons_finished, scope_mandatory in results
    ]


def get_mandatory_summary(user_id: int, schema: str) -> dict:
    """How many modules are mandatory for this user and how many of those they
    finished. Derived on every call, so publishing a new mandatory module shows
    up here without any per-user backfill"""
    mandatory = [m for m in _list_user_trainings(user_id, schema) if m["mandatory"]]

    return {
        "mandatoryTotal": len(mandatory),
        "mandatoryFinished": len([m for m in mandatory if m["finished"]]),
    }


@has_permission(Permission.READ_BASIC_FEATURES)
def list_trainings(user_context: User):
    """List all active trainings visible to the user's schema, ordered by
    position, including lesson counts and completion status"""
    return _list_user_trainings(user_id=user_context.id, schema=user_context.schema)


@has_permission(Permission.READ_BASIC_FEATURES)
def list_training_items(training_id: int, user_context: User):
    """List all active items of a training ordered by position, flagged with
    the current user's completion status"""
    results = training_repository.list_training_items(
        training_id=training_id, user_id=user_context.id
    )

    return [
        {
            "id": item.id,
            "trainingId": item.training_id,
            "title": item.title,
            "text": item.text,
            "video": item.video,
            "position": item.position,
            "questions": item.questions,
            "finished": finished,
        }
        for item, finished in results
    ]


@has_permission(Permission.READ_BASIC_FEATURES)
def finish_training_item(
    training_item_id: int,
    request_data: TrainingItemFinishRequest,
    user_context: User,
):
    """Register that the current user finished a training item, marking the whole
    training module as finished if this was the last pending item, and returning
    the recomputed mandatory summary so the client can update without a re-login"""
    training_repository.finish_training_item(
        training_item_id=training_item_id,
        user_id=user_context.id,
        duration_seconds=request_data.durationSeconds,
    )

    training_id = training_repository.get_training_id_for_item(training_item_id)
    module_finished = False

    if training_repository.is_training_finished(
        training_id=training_id, user_id=user_context.id
    ):
        module_finished = training_repository.finish_training(
            training_id=training_id, user_id=user_context.id
        )

    # the writes above are only staged in the session, and the summary below
    # counts finished lessons and modules
    db.session.flush()

    return {
        "moduleFinished": module_finished,
        "training": get_mandatory_summary(
            user_id=user_context.id, schema=user_context.schema
        ),
    }
