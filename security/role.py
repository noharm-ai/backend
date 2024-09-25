from enum import Enum
from typing import List

from security.permission import Permission


class Role(Enum):

    def __new__(cls, *args, **kwds):
        obj = object.__new__(cls)
        obj._value_ = args[0]
        return obj

    def __init__(self, id: str, permissions: List[Permission]):
        self.id = id
        self.permissions = permissions

    ADMIN = "ADMIN", [
        Permission.ADMIN_DRUGS,
        Permission.ADMIN_DRUGS__OVERWRITE_ATTRIBUTES,
        Permission.ADMIN_EXAMS,
        Permission.ADMIN_EXAMS__COPY,
        Permission.ADMIN_EXAMS__MOST_FREQUENT,
        Permission.ADMIN_FREQUENCIES,
        Permission.ADMIN_INTEGRATION_REMOTE,
        Permission.SCORE_SEGMENT,
        Permission.INTEGRATION_UTILS,
        Permission.ADMIN_INTERVENTION_REASON,
        Permission.INTEGRATION_STATUS,
        Permission.ADMIN_ROUTES,
        Permission.ADMIN_SUBSTANCE_RELATIONS,
        Permission.ADMIN_SUBSTANCES,
        Permission.ADMIN_UNIT_CONVERSION,
        Permission.ADMIN_SEGMENTS,
        Permission.VIEW_REPORTS,
    ]

    CURATOR = "CURATOR", [
        Permission.ADMIN_DRUGS,
        Permission.ADMIN_EXAMS,
        Permission.ADMIN_EXAMS__COPY,
        Permission.ADMIN_EXAMS__MOST_FREQUENT,
        Permission.ADMIN_FREQUENCIES,
        Permission.SCORE_SEGMENT,
        Permission.ADMIN_INTERVENTION_REASON,
        Permission.INTEGRATION_STATUS,
        Permission.ADMIN_ROUTES,
        Permission.ADMIN_SUBSTANCE_RELATIONS,
        Permission.ADMIN_SUBSTANCES,
        Permission.ADMIN_UNIT_CONVERSION,
        Permission.ADMIN_SEGMENTS,
        Permission.VIEW_REPORTS,
    ]

    PRESCRIPTION_ANALIST = "PRESCRIPTION_ANALIST", [
        Permission.CHECK_PRESCRIPTION,
        Permission.VIEW_REPORTS,
    ]

    USER_MANAGER = "USER_MANAGER", [Permission.ADMIN_USERS]

    CONFIG_MANAGER = "CONFIG_MANAGER", [Permission.ADMIN_EXAMS]

    VIEWER = "VIEWER", [Permission.VIEW_REPORTS]

    DISCHARGE_MANAGER = "DISCHARGE_MANAGER", []
