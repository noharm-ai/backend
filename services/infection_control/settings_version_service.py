"""Service: the saved versions of the infection control settings

Each setting of the schema (the antimicrobials without review, the exams of
the timeline) is one memoria record of its kind, written only by its own
service. Saving a change keeps the version it replaced in a record of a
second kind (one version only: the record's value, update_at and update_by
copied as they were), so the settings show when and by whom they were changed
and what they were before. A change made by a user of the NoHarm schema
(Config.NOHARM_SCHEMA) is shown as made by NoHarm, not by the person.

The functions here carry no permission check: the setting's own service
checks it.
"""

from dataclasses import dataclass
from datetime import datetime

from config import Config
from models.appendix import Memory
from models.enums import MemoryEnum
from models.main import db
from repository import user_repository
from repository.infection_control import settings_repository
from utils import dateutils

# who a change made by a NoHarm user is shown as made by
NOHARM_RESPONSIBLE = "NoHarm"


@dataclass
class SettingVersions:
    """A setting's record and the version it replaced (None without them)"""

    kind: MemoryEnum
    previous_kind: MemoryEnum
    record: Memory | None
    previous: Memory | None


def load(kind: MemoryEnum, previous_kind: MemoryEnum) -> SettingVersions:
    """A setting's record and the version it replaced"""
    return SettingVersions(
        kind=kind,
        previous_kind=previous_kind,
        record=settings_repository.get_record(kind),
        previous=settings_repository.get_record(previous_kind),
    )


def save(versions: SettingVersions, value, user_id: int, now: datetime):
    """Write the setting's new value, keeping the version it replaces (a
    setting saved for the first time replaces none). The caller skips a save
    that changes nothing, so the previous version stays the one before"""
    if versions.record is not None:
        if versions.previous is None:
            versions.previous = Memory()
            versions.previous.kind = versions.previous_kind.value
            db.session.add(versions.previous)
        versions.previous.value = versions.record.value
        versions.previous.update = versions.record.update
        versions.previous.user = versions.record.user
    else:
        versions.record = Memory()
        versions.record.kind = versions.kind.value
        db.session.add(versions.record)

    versions.record.value = value
    versions.record.update = now
    versions.record.user = user_id
    db.session.flush()


def responsible_names(versions: SettingVersions) -> dict[int, str]:
    """Who saved each version, by user id: NoHarm for the users of the NoHarm
    schema, the person's name otherwise (a user that no longer exists is
    left out)"""
    id_users = {r.user for r in (versions.record, versions.previous) if r is not None}
    return {
        id_user: NOHARM_RESPONSIBLE if schema == Config.NOHARM_SCHEMA else name
        for id_user, (name, schema) in user_repository.get_user_names_and_schemas(
            id_users
        ).items()
    }


def saved_by(record: Memory | None, names: dict[int, str]) -> dict:
    """When and by whom a version was saved (both None without one)"""
    return {
        "updatedAt": dateutils.to_iso(record.update) if record else None,
        "updatedBy": names.get(record.user) if record else None,
    }
