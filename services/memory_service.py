from flask_jwt_extended import get_jwt_identity

from models.main import db
from models.appendix import *
from models.prescription import *
from models.enums import MemoryEnum
from exception.validation_error import ValidationError


def has_feature(feature):
    user = User.query.get(get_jwt_identity())
    user_features = (
        user.config["features"] if user.config and "features" in user.config else []
    )

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


def save_memory(id, kind, value, user):
    newMem = False
    if id:
        mem = Memory.query.get(id)
        if mem is None:
            raise ValidationError(
                "Memória inexistente",
                "errors.invalidRecord",
                status.HTTP_400_BAD_REQUEST,
            )
    else:
        newMem = True
        mem = Memory()

    mem.kind = kind
    mem.value = value
    mem.update = datetime.today()
    mem.user = user.id

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


def save_unique_memory(kind, value, user):
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

    mem.kind = kind
    mem.value = value
    mem.update = datetime.today()
    mem.user = user.id

    if newMem:
        db.session.add(mem)
        db.session.flush()

    return mem


def is_admin_memory(key):
    return key in [
        MemoryEnum.FEATURES.value,
        MemoryEnum.GETNAME.value,
        MemoryEnum.OAUTH_CONFIG.value,
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
    ]


def get_reports():
    external = get_memory(MemoryEnum.REPORTS.value)
    internal = get_memory(MemoryEnum.REPORTS_INTERNAL.value)

    return {
        "external": external.value if external else [],
        "internal": internal.value if internal else [],
    }
