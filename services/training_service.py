"""Service: training related operations"""

from config import Config
from repository import training_repository, user_attribute_repository, user_repository
from models.enums import FeatureEnum, TrainingAudienceEnum, UserAttributeEnum
from models.main import User, db
from models.requests.training_request import TrainingItemFinishRequest
from decorators.has_permission_decorator import has_permission, Permission
from exception.validation_error import ValidationError
from services import feature_service
from utils import certificateutils, dateutils, status, stringutils


def _is_mandatory(scope_mandatory, audience: str, is_new_user: bool) -> bool:
    """Whether a module is mandatory *for one user*: the schema-level obligation
    resolved in SQL, narrowed here by the module's audience.

    The single source of truth for effective mandatory-ness: nothing else may
    compute it, or the header count, the Training Central page and the manager
    overview would silently disagree.
    """
    return bool(scope_mandatory) and (
        audience == TrainingAudienceEnum.ALL.value or is_new_user
    )


def _is_finished(total_lessons: int, total_lessons_finished: int) -> bool:
    """Whether a module counts as finished: every one of its *active* lessons is
    done. Not the completion record, which never reopens - this is the reading
    the support-ticket gate is built on, so a module that gained lessons after
    the user finished it is pending again.
    """
    return total_lessons > 0 and total_lessons_finished == total_lessons


def _mandatory_summary(user_modules: list) -> dict:
    """Obligation counters for one user, from their already resolved module list.

    The env flag gates *obligations*, not content: with it off nobody owes
    anything, while the module lists still return whatever modules exist - and
    still tag them mandatory, which is a property of the module rather than of
    the obligation.
    """
    if not Config.FEATURE_USER_ONBOARDING:
        return {"mandatoryTotal": 0, "mandatoryFinished": 0}

    mandatory = [m for m in user_modules if m["mandatory"]]

    return {
        "mandatoryTotal": len(mandatory),
        "mandatoryFinished": len([m for m in mandatory if m["finished"]]),
    }


def _list_user_trainings(user_id: int, schema: str) -> list:
    """Modules visible to the given schema, each flagged with whether it is
    mandatory for this user and whether they already finished it.

    Not permission decorated, so it can also run during login.
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
            "mandatory": _is_mandatory(
                scope_mandatory=scope_mandatory,
                audience=item.audience,
                is_new_user=is_new_user,
            ),
            "totalLessons": total_lessons,
            "totalLessonsFinished": total_lessons_finished,
            "finished": _is_finished(total_lessons, total_lessons_finished),
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
    """
    if not Config.FEATURE_USER_ONBOARDING:
        # short circuit: this runs on the support-ticket gate path, and with no
        # obligations to count there is nothing to ask the database for
        return _mandatory_summary([])

    return _mandatory_summary(_list_user_trainings(user_id=user_id, schema=schema))


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


@has_permission(Permission.READ_USERS)
def get_training_overview(user_context: User):
    """Training progress of every user of the schema, for the managers who have
    to follow it.

    Resolved in a fixed number of set based queries rather than by calling
    _list_user_trainings once per user: a schema has hundreds of users, and the
    per-user path issues its own subqueries.

    The numbers here go through the same _is_mandatory / _is_finished rules the
    user's own Training Central page and the support-ticket gate use, so a
    manager never reads "done" for someone the system still considers pending.
    """
    modules = training_repository.list_schema_trainings(schema=user_context.schema)
    users = user_repository.get_admin_users_list(schema=user_context.schema)

    training_ids = [module.id for module, _, _ in modules]
    user_ids = [user.id for user, _ in users]

    # bulk equivalent of the per-user onboarding lookup in _list_user_trainings:
    # the presence of the row is what marks a user as new
    new_user_ids = user_attribute_repository.list_users_with_attribute(
        user_ids=user_ids, kind=UserAttributeEnum.ONBOARDING.value
    )

    lessons_finished = {
        (row_user_id, row_training_id): count
        for row_user_id, row_training_id, count in (
            training_repository.list_lessons_finished_by_user(
                training_ids=training_ids, user_ids=user_ids
            )
        )
    }

    completions = {
        (row_user_id, row_training_id): completed_at
        for row_user_id, row_training_id, completed_at in (
            training_repository.list_training_completions(
                training_ids=training_ids, user_ids=user_ids
            )
        )
    }

    last_activity = dict(
        training_repository.list_last_activity(
            training_ids=training_ids, user_ids=user_ids
        )
    )

    hide_names = feature_service.has_user_feature(FeatureEnum.HIDE_NAMES)

    user_results = []

    for user, _segments in users:
        is_new_user = user.id in new_user_ids
        user_modules = []

        for module, total_lessons, scope_mandatory in modules:
            total_lessons_finished = lessons_finished.get((user.id, module.id), 0)

            user_modules.append(
                {
                    "id": module.id,
                    "mandatory": _is_mandatory(
                        scope_mandatory=scope_mandatory,
                        audience=module.audience,
                        is_new_user=is_new_user,
                    ),
                    "totalLessons": total_lessons,
                    "totalLessonsFinished": total_lessons_finished,
                    "finished": _is_finished(total_lessons, total_lessons_finished),
                    # when the module was first completed, if ever. A module that
                    # later gained lessons keeps this date while going back to
                    # finished=False, which is how the overview shows "reopened"
                    "completedAt": dateutils.to_iso(
                        completions.get((user.id, module.id))
                    ),
                }
            )

        optional = [m for m in user_modules if not m["mandatory"]]

        user_results.append(
            {
                "id": user.id,
                "name": "***" if hide_names else user.name,
                "email": "***" if hide_names else user.email,
                "active": user.active,
                "newUser": is_new_user,
                **_mandatory_summary(user_modules),
                "optionalTotal": len(optional),
                "optionalFinished": len([m for m in optional if m["finished"]]),
                "totalLessons": sum(m["totalLessons"] for m in user_modules),
                "totalLessonsFinished": sum(
                    m["totalLessonsFinished"] for m in user_modules
                ),
                "lastActivityAt": dateutils.to_iso(last_activity.get(user.id)),
                "modules": user_modules,
            }
        )

    return {
        "modules": [
            {
                "id": module.id,
                "title": module.title,
                "position": module.position,
                "totalLessons": total_lessons,
                "audience": module.audience,
                # the schema level obligation. Whether it actually lands on a
                # given user also depends on the audience, which is why every
                # per-user entry above carries its own mandatory flag
                "mandatory": bool(scope_mandatory),
            }
            for module, total_lessons, scope_mandatory in modules
        ],
        # aggregates are deliberately left to the client: it filters the list
        # (active users, one module) and any total computed here would disagree
        # with the rows on screen
        "users": user_results,
    }


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


def validate_certificate(validation_code: str) -> dict:
    """Public certificate confirmation. Deliberately undecorated and without a
    user_context: this is the only training entry point reachable anonymously,
    and has_permission would try to resolve a user that is not logged in.

    Confirmation-only by design. It returns a masked name and never the full
    one, never the user id, e-mail, schema or training id: whoever calls this
    already holds the printed certificate, so the endpoint only has to say
    "yes, this is genuine" - it is not a place to hand out anything new.

    An unknown or malformed code answers valid=False with HTTP 200 rather than
    404: on a public page a typo is the expected case, not an error, and one
    shape of answer leaves no oracle separating "well formed but unknown" from
    "junk".
    """
    normalized = certificateutils.normalize_code(validation_code)

    if len(normalized) != certificateutils.CODE_LENGTH:
        return {"valid": False}

    result = training_repository.get_training_user_by_code(validation_code=normalized)

    if result is None:
        return {"valid": False}

    record, training, user = result

    # the count comes from the list rather than its own query, so the number
    # and the lessons behind it can never disagree
    lessons = training_repository.list_finished_lessons(
        training_id=training.id, user_id=user.id
    )

    return {
        "valid": True,
        "maskedName": stringutils.mask_person_name(user.name),
        "trainingTitle": training.title,
        "totalHours": training.total_hours,
        "totalLessons": len(lessons),
        "lessons": lessons,
        "completedAt": dateutils.to_iso(record.created_at),
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
        # grouped for printing; the public lookup normalizes the dashes away
        "validationCode": certificateutils.format_code(record.validation_code),
    }
