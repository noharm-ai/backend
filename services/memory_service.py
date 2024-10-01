from flask_jwt_extended import get_jwt_identity
from datetime import datetime

from models.main import db, User
from models.appendix import Memory
from models.enums import MemoryEnum
from exception.validation_error import ValidationError
from decorators.has_permission_decorator import has_permission, Permission
from utils import status


@has_permission(Permission.READ_BASIC_FEATURES)
def get_memory_by_kind(kind: str):
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


def has_feature(feature: str):
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
    features = db.session.query(Memory).filter(Memory.kind == "features").first()

    if features is None:
        return False

    if feature not in features.value:
        return False

    return True


def get_memory(key):
    return db.session.query(Memory).filter(Memory.kind == key).first()


def get_by_kind(kinds) -> dict:
    memory_itens = {}
    records = db.session.query(Memory).filter(Memory.kind.in_(kinds)).all()

    for r in records:
        memory_itens[r.kind] = r.value

    return memory_itens


@has_permission(Permission.WRITE_BASIC_FEATURES)
def save_memory(id, kind, value, user_context: User):
    newMem = False
    if id:
        mem = Memory.query.get(id)
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
        MemoryEnum.MAP_ORIGIN_CUSTOM.value,
        MemoryEnum.CUSTOM_FORMS.value,
    ]


def is_private(key):
    private_keys = ["config-signature", "filter-private", "user-preferences"]

    for k in private_keys:
        if k in key:
            return True

    return False


@has_permission(Permission.READ_REPORTS)
def get_reports():
    external = get_memory(MemoryEnum.REPORTS.value)
    internal = get_memory(MemoryEnum.REPORTS_INTERNAL.value)

    return {
        "external": external.value if external else [],
        "internal": internal.value if internal else [],
    }
