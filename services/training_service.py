"""Service: training related operations"""

from repository import training_repository
from models.main import User
from models.requests.training_request import TrainingItemFinishRequest
from decorators.has_permission_decorator import has_permission, Permission


@has_permission(Permission.READ_BASIC_FEATURES)
def list_trainings(user_context: User):
    """List all active trainings ordered by position, including lesson
    counts and completion status for the current user"""
    results = training_repository.list_trainings(user_id=user_context.id)

    return [
        {
            "id": item.id,
            "page": item.page,
            "title": item.title,
            "description": item.description,
            "position": item.position,
            "mandatory": item.mandatory,
            "totalLessons": total_lessons,
            "totalLessonsFinished": total_lessons_finished,
            "finished": total_lessons > 0
            and total_lessons_finished == total_lessons,
        }
        for item, total_lessons, total_lessons_finished in results
    ]


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
    """Register that the current user finished a training item, marking the
    whole training module as finished if this was the last pending item"""
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

    return {"moduleFinished": module_finished}
