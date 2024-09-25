from enum import Enum


class Permission(Enum):
    # ADMIN
    ADMIN_DRUGS = "admin drug attributes"
    ADMIN_EXAMS = "admin exams"
    ADMIN_USERS = "admin users"

    CHECK_PRESCRIPTION = "check prescriptions"
