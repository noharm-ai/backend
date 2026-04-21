from datetime import datetime, timedelta
from typing import List

from markupsafe import escape as escape_html
from sqlalchemy import func

from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from models.appendix import Memory
from models.enums import FeatureEnum, MemoryEnum
from models.main import User, db
from models.prescription import Prescription, PrescriptionDrug
from utils import status

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
    MemoryEnum.TRANSCRIPTION_FIELDS.value,
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


@has_permission(Permission.ADMIN_APP_FEATURES)
def update_memory(
    key,
    kind,
    value,
    user_context: User,
    user_permissions: List[Permission],
    unique=False,
):

    if unique:
        memory_item = db.session.query(Memory).filter(Memory.kind == kind).first()
    else:
        memory_item = (
            db.session.query(Memory)
            .filter(Memory.key == key)
            .filter(Memory.kind == kind)
            .first()
        )

    if kind == MemoryEnum.FEATURES.value:
        existing_features = memory_item.value if memory_item is not None else []
        protected = {
            FeatureEnum.PRIMARY_CARE.value,
            FeatureEnum.OAUTH.value,
            FeatureEnum.PATIENT_DAY_OUTPATIENT_FLOW.value,
        }
        changed_protected = (
            set(value or []).symmetric_difference(set(existing_features or []))
            & protected
        )
        if changed_protected and Permission.INTEGRATION_UTILS not in user_permissions:
            raise ValidationError(
                f"Você não possui permissão para editar estas features: {', '.join(sorted(changed_protected))}",
                "errors.unauthorized",
                status.HTTP_403_FORBIDDEN,
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
