from datetime import datetime, timedelta
from markupsafe import escape as escape_html
from utils import status
from sqlalchemy import func
from typing import List

from models.main import db, User
from models.appendix import Memory
from models.prescription import Prescription, PrescriptionDrug
from models.enums import MemoryEnum
from decorators.has_permission_decorator import has_permission, Permission
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


@has_permission(Permission.INTEGRATION_UTILS, Permission.ADMIN_ROUTES)
def get_admin_entries(kinds=[]):
    return get_memory_itens(kinds)


def get_memory_itens(kinds):
    memory_itens = db.session.query(Memory).filter(Memory.kind.in_(kinds)).all()

    itens = []
    foundKinds = []
    for i in memory_itens:
        foundKinds.append(i.kind)
        itens.append({"key": i.key, "kind": i.kind, "value": i.value})

    for k in kinds:
        if k not in foundKinds:
            if k == "map-schedules":
                schedules = []
                results = (
                    db.session.query(
                        func.distinct(PrescriptionDrug.interval).label("interval")
                    )
                    .join(
                        Prescription, PrescriptionDrug.idPrescription == Prescription.id
                    )
                    .filter(Prescription.date > datetime.now() - timedelta(days=2))
                    .order_by(PrescriptionDrug.interval)
                    .limit(500)
                    .all()
                )
                for s in results:
                    if s.interval != None and s.interval != "":
                        schedules.append(
                            {
                                "id": s.interval,
                                "value": s.interval,
                            }
                        )

                itens.append({"key": None, "kind": escape_html(k), "value": schedules})

            else:
                itens.append({"key": None, "kind": escape_html(k), "value": []})

    return itens


@has_permission(Permission.INTEGRATION_UTILS, Permission.ADMIN_ROUTES)
def update_memory(
    key,
    kind,
    value,
    user_context: User,
    user_permissions: List[Permission],
    unique=False,
):
    authorized = True
    if kind in KIND_ADMIN and Permission.INTEGRATION_UTILS not in user_permissions:
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
    memory_item.user = user_context.id

    db.session.add(memory_item)
    db.session.flush()

    return key
