from flask_api import status
from sqlalchemy import or_

from models.main import db
from models.appendix import *
from models.prescription import *
from models.enums import MemoryEnum, RoleEnum

from exception.validation_error import ValidationError

KIND_ADMIN = [
    MemoryEnum.FEATURES.value,
    MemoryEnum.REPORTS.value,
    MemoryEnum.GETNAME.value,
    MemoryEnum.ADMISSION_REPORTS.value,
    MemoryEnum.MAP_ORIGIN_DRUG.value,
    MemoryEnum.MAP_ORIGIN_SOLUTION.value,
    MemoryEnum.MAP_ORIGIN_PROCEDURE.value,
    MemoryEnum.MAP_ORIGIN_DIET.value,
    MemoryEnum.MAP_ORIGIN_CUSTOM.value,
]

KIND_ROUTES = [
    MemoryEnum.MAP_IV.value,
    MemoryEnum.MAP_TUBE.value,
    MemoryEnum.MAP_ROUTES.value,
]


def get_admin_entries(user, kinds=[]):
    roles = user.config["roles"] if user.config and "roles" in user.config else []
    if RoleEnum.ADMIN.value not in roles and RoleEnum.TRAINING.value not in roles:
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    return _get_memory_itens(kinds)


def _get_memory_itens(kinds):
    memory_itens = db.session.query(Memory).filter(Memory.kind.in_(kinds)).all()

    itens = []
    foundKinds = []
    for i in memory_itens:
        foundKinds.append(i.kind)
        itens.append({"key": i.key, "kind": i.kind, "value": i.value})

    for k in kinds:
        if k not in foundKinds:
            itens.append({"key": None, "kind": k, "value": []})

    return itens


def update_memory(key, kind, value, user, unique=False):
    roles = user.config["roles"] if user.config and "roles" in user.config else []
    authorized = True
    if kind in KIND_ADMIN and RoleEnum.ADMIN.value not in roles:
        authorized = False
    elif RoleEnum.ADMIN.value not in roles and RoleEnum.TRAINING.value not in roles:
        authorized = False

    if not authorized:
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    if unique:
        memory_item = db.session.query(Memory).filter(Memory.kind == kind).first()
    else:
        memory_item = (
            db.session.query(Memory)
            .filter(Memory.key == key)
            .filter(Memory.kind == kind)
            .first()
        )

    if memory_item == None:
        memory_item = Memory()
        memory_item.kind = kind
    else:
        # bkp
        memory_bkp = Memory()
        memory_bkp.kind = memory_item.kind + "_bkp"
        memory_bkp.value = memory_item.value
        memory_bkp.update = memory_item.update
        memory_bkp.user = memory_item.user
        db.session.add(memory_bkp)

    # update
    memory_item.value = value
    memory_item.update = datetime.today()
    memory_item.user = user.id

    db.session.add(memory_item)
    db.session.flush()

    return key
