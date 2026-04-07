"""Service: memory related operations"""

from datetime import datetime

from flask_jwt_extended import get_jwt_identity

from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from models.appendix import Memory
from models.enums import MemoryEnum
from models.main import User, db
from utils import dateutils, status

EDITABLE_KINDS = ["tpl-care-plan"]


@has_permission(Permission.READ_BASIC_FEATURES)
def get_memory_by_kind(kind: str):
    """Get all memory records of a given kind. Admin-restricted kinds are blocked."""
    if is_admin_memory(kind) and not kind == MemoryEnum.CUSTOM_FORMS.value:
        raise ValidationError(
            "Memória inexistente",
            "errors.invalidRecord",
            status.HTTP_400_BAD_REQUEST,
        )

    memList = Memory.query.filter(Memory.kind == kind).all()

    results = []
    for m in memList:
        results.append({"key": m.key, "value": m.value})

    return results


@has_permission(Permission.READ_BASIC_FEATURES)
def get_editable_memories():
    """Get all memory records whose kind is in EDITABLE_KINDS."""
    mem_list = Memory.query.filter(Memory.kind.in_(EDITABLE_KINDS)).all()

    results = []
    for m in mem_list:
        results.append(
            {
                "key": m.key,
                "kind": m.kind,
                "value": m.value,
                "updatedAt": dateutils.to_iso(m.update),
            }
        )

    return results


@has_permission(Permission.READ_BASIC_FEATURES)
def get_memory_by_id(id: int):
    """Get a single memory record by primary key. Only EDITABLE_KINDS are accessible."""
    mem = db.session.get(Memory, id)
    if mem is None or mem.kind not in EDITABLE_KINDS:
        raise ValidationError(
            "Memória inexistente",
            "errors.invalidRecord",
            status.HTTP_400_BAD_REQUEST,
        )

    return {
        "key": mem.key,
        "kind": mem.kind,
        "value": mem.value,
        "updatedAt": dateutils.to_iso(mem.update),
    }


def has_feature(feature: str):
    """Check if a feature is enabled for the current user or globally in the features memory."""
    try:
        user = User.find(get_jwt_identity())
        user_features = (
            user.config["features"] if user.config and "features" in user.config else []
        )
    except:
        user_features = []

    if feature in user_features:
        return True

    features = db.session.query(Memory).filter(Memory.kind == "features").first()

    if features is None:
        return False

    if feature not in features.value:
        return False

    return True


def has_feature_nouser(feature):
    """Check if a feature is enabled globally (no user context required)."""
    features = db.session.query(Memory).filter(Memory.kind == "features").first()

    if features is None:
        return False

    if feature not in features.value:
        return False

    return True


def get_memory(key):
    """Get the first memory record matching the given kind key."""
    return db.session.query(Memory).filter(Memory.kind == key).first()


def get_by_kind(kinds) -> dict:
    """Get memory values indexed by kind for a list of kind keys."""
    memory_itens = {}
    records = db.session.query(Memory).filter(Memory.kind.in_(kinds)).all()

    for r in records:
        memory_itens[r.kind] = r.value

    return memory_itens


@has_permission(Permission.WRITE_CUSTOM_FORMS)
def save_custom_form(id: int | None, value, user_context: User):
    """Create or update a custom-forms memory record."""
    return save_memory(
        id=id,
        kind=MemoryEnum.CUSTOM_FORMS.value,
        value=value,
        user_context=user_context,
    )


@has_permission(Permission.WRITE_BASIC_FEATURES)
def save_memory(id, kind, value, user_context: User):
    """Create or update a memory record. Admin kinds and unauthorized private records are rejected."""
    newMem = False
    if id:
        mem = db.session.get(Memory, id)
        if mem is None:
            raise ValidationError(
                "Memória inexistente",
                "errors.invalidRecord",
                status.HTTP_400_BAD_REQUEST,
            )

        if is_private(key=kind) and user_context.id != mem.user:
            raise ValidationError(
                "Usuário não possui permissão para alterar este registro",
                "errors.unauthorizedUser",
                status.HTTP_401_UNAUTHORIZED,
            )

    else:
        newMem = True
        if kind in EDITABLE_KINDS and get_memory(kind) is not None:
            raise ValidationError(
                "Já existe um registro com este tipo",
                "errors.invalidParam",
                status.HTTP_400_BAD_REQUEST,
            )
        mem = Memory()

    mem.kind = kind
    mem.value = value
    mem.update = datetime.today()
    mem.user = user_context.id

    if is_admin_memory(mem.kind):
        raise ValidationError(
            "Usuário não possui permissão para alterar este registro",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    if newMem:
        db.session.add(mem)
        db.session.flush()

    return mem


@has_permission(Permission.WRITE_BASIC_FEATURES)
def save_unique_memory(kind, value, user_context: User):
    """Create or update a memory record ensuring only one record exists per kind."""
    if is_admin_memory(kind):
        raise ValidationError(
            "Usuário não possui permissão para alterar este registro",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    newMem = False

    mem = get_memory(kind)
    if mem is None:
        newMem = True
        mem = Memory()
    else:
        if is_private(key=kind) and user_context.id != mem.user:
            raise ValidationError(
                "Usuário não possui permissão para alterar este registro",
                "errors.unauthorizedUser",
                status.HTTP_401_UNAUTHORIZED,
            )

    mem.kind = kind
    mem.value = value
    mem.update = datetime.today()
    mem.user = user_context.id

    if newMem:
        db.session.add(mem)
        db.session.flush()

    return mem


def is_admin_memory(key):
    """Return True if the kind key is restricted to admin operations."""
    return key in [
        MemoryEnum.FEATURES.value,
        MemoryEnum.GETNAME.value,
        MemoryEnum.OAUTH_CONFIG.value,  # deprecated
        MemoryEnum.OAUTH_KEYS.value,
        MemoryEnum.PRESMED_FORM.value,
        MemoryEnum.REPORTS.value,
        MemoryEnum.REPORTS_INTERNAL.value,
        MemoryEnum.ADMISSION_REPORTS.value,
        MemoryEnum.SUMMARY_CONFIG.value,
        MemoryEnum.MAP_IV.value,
        MemoryEnum.MAP_TUBE.value,
        MemoryEnum.MAP_ORIGIN_DRUG.value,
        MemoryEnum.MAP_ORIGIN_SOLUTION.value,
        MemoryEnum.MAP_ORIGIN_PROCEDURE.value,
        MemoryEnum.MAP_ORIGIN_DIET.value,
        MemoryEnum.MAP_ORIGIN_MATERIAL.value,
        MemoryEnum.MAP_ORIGIN_CUSTOM.value,
        MemoryEnum.TRANSCRIPTION_FIELDS.value,
    ]


def is_private(key):
    """Return True if the kind key is user-scoped (private to its owner)."""
    private_keys = [
        "config-signature",
        "filter-private",
        "user-preferences",
        "clinical-notes-private",
    ]

    for k in private_keys:
        if k in key:
            return True

    return False
