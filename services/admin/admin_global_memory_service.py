"""Service: admin global memory related operations"""

from datetime import datetime

from utils import status
from models.main import db, User
from models.appendix import GlobalMemory
from models.requests.admin.admin_global_memory_request import (
    GlobalMemoryItensRequest,
    UpdateGlobalMemoryRequest,
)
from decorators.has_permission_decorator import has_permission, Permission
from exception.validation_error import ValidationError


@has_permission(Permission.ADMIN_NZERO)
def get_entries(request_data: GlobalMemoryItensRequest):
    """Get records from global memory"""

    memory_itens = (
        db.session.query(GlobalMemory)
        .filter(GlobalMemory.kind.in_(request_data.kinds))
        .all()
    )

    itens = []
    for i in memory_itens:
        itens.append({"key": i.key, "kind": i.kind, "value": i.value})

    return itens


@has_permission(Permission.ADMIN_NZERO)
def update_memory(request_data: UpdateGlobalMemoryRequest, user_context: User):
    """Update a global memory record"""
    memory_item = (
        db.session.query(GlobalMemory)
        .filter(GlobalMemory.key == request_data.key)
        .first()
    )

    if not memory_item:
        raise ValidationError(
            "Item de memória inválido",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    # bkp
    memory_bkp = GlobalMemory()
    memory_bkp.kind = memory_item.kind + "_bkp"
    memory_bkp.value = memory_item.value
    memory_bkp.update = memory_item.update
    memory_bkp.user = memory_item.user
    db.session.add(memory_bkp)

    # update
    memory_item.value = request_data.value
    memory_item.update = datetime.today()
    memory_item.user = user_context.id

    db.session.add(memory_item)
    db.session.flush()

    return memory_item.key
