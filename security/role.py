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

    ADMIN = "ADMIN", [Permission.ADMIN_DRUGS, Permission.ADMIN_EXAMS]

    CURATOR = "CURATOR", [Permission.ADMIN_DRUGS, Permission.ADMIN_EXAMS]

    PHARMA = "PHARMA", [Permission.CHECK_PRESCRIPTION]

    ADMIN_USERS = "ADMIN_USERS", [Permission.ADMIN_USERS]

    ADMIN_CONFIG = "ADMIN_CONFIG", [Permission.ADMIN_EXAMS]

    RESEARCHER = "RESEARCHER", []

    DOCTOR = "DOCTOR", []
