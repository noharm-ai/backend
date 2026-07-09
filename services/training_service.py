"""Service: training related operations"""

from repository import training_repository
from models.main import User
from decorators.has_permission_decorator import has_permission, Permission


@has_permission(Permission.READ_BASIC_FEATURES)
def list_trainings(user_context: User):
    """List all active trainings ordered by position"""
    results = training_repository.list_trainings()

    return [
        {
            "id": item.id,
            "page": item.page,
            "title": item.title,
            "description": item.description,
            "position": item.position,
        }
        for item in results
    ]


@has_permission(Permission.READ_BASIC_FEATURES)
def list_training_items(training_id: int, user_context: User):
    """List all active items of a training ordered by position"""
    results = training_repository.list_training_items(training_id=training_id)

    return [
        {
            "id": item.id,
            "trainingId": item.training_id,
            "title": item.title,
            "text": item.text,
            "video": item.video,
            "position": item.position,
            "questions": item.questions,
        }
        for item in results
    ]
