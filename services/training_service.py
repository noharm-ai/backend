"""Service: training related operations"""

from config import Config
from repository import training_repository, user_attribute_repository
from models.enums import TrainingAudienceEnum, UserAttributeEnum
from models.main import User, db
from models.requests.training_request import TrainingItemFinishRequest
from decorators.has_permission_decorator import has_permission, Permission
from exception.validation_error import ValidationError
from utils import dateutils, status


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
            # backed by the completion record, not the counts above: new
            # lessons reopen the module but never revoke the certificate
            "certificateAvailable": certificate_available > 0,
        }
        for (
            item,
            total_lessons,
            total_lessons_finished,
            scope_mandatory,
            certificate_available,
        ) in results
    ]


def get_mandatory_summary(user_id: int, schema: str) -> dict:
    """How many modules are mandatory for this user and how many of those they
    finished. Derived on every call, so publishing a new mandatory module shows
    up here without any per-user backfill.

    The env flag gates *obligations*, not content: with it off nobody owes
    anything, while list_trainings still returns whatever modules exist.
    """
    if not Config.FEATURE_USER_ONBOARDING:
        return {"mandatoryTotal": 0, "mandatoryFinished": 0}

    mandatory = [m for m in _list_user_trainings(user_id, schema) if m["mandatory"]]

    return {
        "mandatoryTotal": len(mandatory),
        "mandatoryFinished": len([m for m in mandatory if m["finished"]]),
    }


def has_pending_mandatory_training(user_id: int, schema: str) -> bool:
    """Whether the user still owes mandatory training. The gate other features
    (support tickets) consult, so they never re-derive the rule"""
    summary = get_mandatory_summary(user_id=user_id, schema=schema)

    return summary["mandatoryFinished"] < summary["mandatoryTotal"]


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


@has_permission(Permission.READ_BASIC_FEATURES)
def get_training_certificate(training_id: int, user_context: User):
    """Certificate data for a training module the current user finished. The
    treinamento_usuario record is the single proof of completion: once earned,
    the certificate stays valid even if the module later gains new lessons or
    is deactivated — the current lesson counts are deliberately not checked."""
    training = training_repository.get_training(training_id=training_id)

    if training is None:
        raise ValidationError(
            "Treinamento inválido",
            "errors.invalidRecord",
            status.HTTP_400_BAD_REQUEST,
        )

    record = training_repository.get_training_user(
        training_id=training_id, user_id=user_context.id
    )

    if record is None:
        raise ValidationError(
            "Módulo de treinamento ainda não concluído",
            "errors.trainingNotFinished",
            status.HTTP_400_BAD_REQUEST,
        )

    # user_context is a JWT stub without the name column
    user = db.session.query(User).filter(User.id == user_context.id).first()

    return {
        "userName": user.name,
        "trainingId": training.id,
        "trainingTitle": training.title,
        # the module's official workload, a property of the module itself, so
        # unlike the lesson count it is not snapshotted at completion time
        "totalHours": training.total_hours,
        # what the user completed back then, not the module's current content
        "totalLessons": training_repository.count_finished_lessons(
            training_id=training_id, user_id=user_context.id
        ),
        "completedAt": dateutils.to_iso(record.created_at),
    }
