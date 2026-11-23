"""Repository: the records of the infection control settings (memoria)"""

from models.appendix import Memory
from models.enums import MemoryEnum
from models.main import db


def get_record(kind: MemoryEnum) -> Memory | None:
    """The memoria record of a setting (or of the version it replaced) by its
    kind: one per schema, the oldest if there were more"""
    return (
        db.session.query(Memory)
        .filter(Memory.kind == kind.value)
        .order_by(Memory.key)
        .first()
    )
