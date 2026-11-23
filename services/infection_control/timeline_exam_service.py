"""Service: the exams the antimicrobial timeline of an admission opens with

The infection control page plots some exams under the courses, a row each,
picked by their reference (segmentoexame.tpexame_ref, the same in every
schema) among the patient's results; the users add others from the timeline.
Each schema chooses which and in what order (models/infection_control_config.py,
TimelineExamsData), in its memoria (kind
MemoryEnum.INFECTION_CONTROL_TIMELINE_EXAMS, an admin kind: only this service
writes it, and only for WRITE_INFECTION_CONTROL). Without a record (or with
one that can't be read) the timeline opens with DEFAULT_TIMELINE_EXAMS.

The admission view sends the list (load) with the timeline, or None while
the schema never chose (the page plots its default, taking CKD-EPI or
CKD-EPI 2021, the first the patient has). The settings
offer the references the schema's active exams are mapped to; a reference
kept from before, or one of the default list, may stay even if the schema
maps no exam to it (shown unavailable: the timeline plots it only for a
patient with results of it). Going back to the default saves no copy of it:
the record says it follows the default (exams None), so a later change of
DEFAULT_TIMELINE_EXAMS reaches the schema, and the change is still a version
with who made it. Saving a change keeps the version it replaces (kind
INFECTION_CONTROL_TIMELINE_EXAMS_PREVIOUS, see settings_version_service); a
save that changes nothing writes nothing.
"""

from datetime import datetime

from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from models.enums import FeatureEnum, MemoryEnum
from models.infection_control_config import (
    DEFAULT_TIMELINE_EXAMS,
    TimelineExamsData,
    parse_timeline_exams,
)
from models.main import User
from models.requests.infection_control_request import TimelineExamsSaveRequest
from repository import exams_repository
from repository.infection_control import settings_repository
from services import feature_service
from services.infection_control import settings_version_service
from services.infection_control.settings_version_service import SettingVersions
from utils import status


def _choice(record) -> list[str] | None:
    """The references a record chose, in order; None when it follows the
    default (no record, one saying so, or one that can't be read)"""
    data = parse_timeline_exams(record.value if record else None)
    return data.exams if data is not None else None


def load() -> list[str] | None:
    """The references the timeline opens with, in order; None while the schema
    follows the default, so the page keeps the default as it plots it (CKD-EPI
    or, where configured instead, CKD-EPI 2021: one of them, never both). No
    permission check: the admission view has one"""
    return _choice(
        settings_repository.get_record(MemoryEnum.INFECTION_CONTROL_TIMELINE_EXAMS)
    )


def _versions() -> SettingVersions:
    """The list kept and the version it replaced"""
    return settings_version_service.load(
        kind=MemoryEnum.INFECTION_CONTROL_TIMELINE_EXAMS,
        previous_kind=MemoryEnum.INFECTION_CONTROL_TIMELINE_EXAMS_PREVIOUS,
    )


def _check_feature():
    """The infection control must be on for the schema"""
    if not feature_service.has_feature(FeatureEnum.INFECTION_CONTROL):
        raise ValidationError(
            "Controle de infecção não está habilitado",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )


def _view(versions: SettingVersions) -> dict:
    """The exams in force (the default while the schema follows it), when and
    by whom they were saved, the version they replaced (previous, None without
    one), the default list and the exams the schema offers (options), each
    with its name"""
    catalog = exams_repository.get_schema_exam_refs()
    record, previous_record = versions.record, versions.previous
    choice = _choice(record)
    previous_choice = _choice(previous_record)
    in_force = choice if choice is not None else list(DEFAULT_TIMELINE_EXAMS)

    listed = set(in_force) | set(DEFAULT_TIMELINE_EXAMS) | set(previous_choice or [])
    names = {
        **exams_repository.get_global_exam_names(listed - set(catalog)),
        **catalog,
    }
    responsible = settings_version_service.responsible_names(versions)

    def exams(refs: list[str]) -> list[dict]:
        """The references with their names, and whether the schema maps an
        exam to them"""
        return [
            {"examRef": ref, "name": names.get(ref, ref), "available": ref in catalog}
            for ref in refs
        ]

    return {
        "exams": exams(in_force),
        "default": choice is None,
        **settings_version_service.saved_by(record, responsible),
        "previous": (
            {
                "exams": exams(
                    previous_choice
                    if previous_choice is not None
                    else list(DEFAULT_TIMELINE_EXAMS)
                ),
                "default": previous_choice is None,
                **settings_version_service.saved_by(previous_record, responsible),
            }
            if previous_record is not None
            else None
        ),
        "defaultExams": exams(list(DEFAULT_TIMELINE_EXAMS)),
        "options": [{"examRef": ref, "name": name} for ref, name in catalog.items()],
    }


@has_permission(Permission.READ_INFECTION_CONTROL)
def get_timeline_exams():
    """The exams the antimicrobial timeline opens with"""
    _check_feature()

    return _view(_versions())


@has_permission(Permission.WRITE_INFECTION_CONTROL)
def save_timeline_exams(request_data: TimelineExamsSaveRequest, user_context: User):
    """Replace the exams the antimicrobial timeline opens with, or go back to
    following the default (request `default`), keeping the version replaced.
    An exam added must be one the schema offers or one of the default list
    (one kept may stay, so the others can still be saved)"""
    _check_feature()

    versions = _versions()
    current = _choice(versions.record)
    requested = None if request_data.default else request_data.exams

    if requested is not None:
        in_force = current if current is not None else DEFAULT_TIMELINE_EXAMS
        added = set(requested) - set(in_force) - set(DEFAULT_TIMELINE_EXAMS)
        if added - set(exams_repository.get_schema_exam_refs()):
            raise ValidationError(
                "Exame não configurado neste hospital",
                "errors.invalidRecord",
                status.HTTP_400_BAD_REQUEST,
            )

    if requested == current:
        # nothing changed: the previous version stays the one before
        return _view(versions)

    settings_version_service.save(
        versions,
        value=TimelineExamsData(exams=requested).model_dump(),
        user_id=user_context.id,
        now=datetime.now(),
    )

    return _view(versions)
