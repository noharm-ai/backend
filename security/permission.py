from enum import Enum


class Permission(Enum):
    ADMIN_DRUGS = "admin drug attributes"
    ADMIN_DRUGS__OVERWRITE_ATTRIBUTES = "permits overwriting attributes on copy"

    ADMIN_EXAMS = "admin exams"
    ADMIN_EXAMS__COPY = "copy exams from other segments"
    ADMIN_EXAMS__MOST_FREQUENT = "get most frequent exams"

    ADMIN_FREQUENCIES = "admin frequency configs"
    ADMIN_ROUTES = "admin routes configs"
    ADMIN_SUBSTANCE_RELATIONS = "admin substance relations"
    ADMIN_SUBSTANCES = "admin substances"
    ADMIN_SEGMENTS = "admin segments"
    ADMIN_UNIT_CONVERSION = "admin unit conversions"

    ADMIN_PATIENT = "admin extra patient configs"

    ADMIN_USERS = "admin users"

    ADMIN_INTEGRATION_REMOTE = "grants integration remote access"

    ADMIN_INTERVENTION_REASON = "admin intervention reason recordss"

    WRITE_SEGMENT_SCORE = "grant permission to generate score to the entire segment"

    INTEGRATION_UTILS = "grants permission to actions to help integration process"
    INTEGRATION_STATUS = "grants access to view current integration status"

    READ_REPORTS = "grants permission to view reports"

    READ_PRESCRIPTION = "view prescription"
    WRITE_PRESCRIPTION = "write prescription"

    WRITE_DRUG_ATTRIBUTES = "write permission on drug drug attributes"
    WRITE_DRUG_SCORE = "write permission to generate/edit score"

    READ_BASIC_FEATURES = "grants use of basic features"
    WRITE_BASIC_FEATURES = "grants use of basic features"

    READ_DISCHARGE_SUMMARY = "grants access to discharge summary"
    WRITE_DISCHARGE_SUMMARY = "grants access to discharge summary"

    READ_SUPPORT = "permission to view support tickets"
    WRITE_SUPPORT = "permission to create support tickets"

    READ_USERS = "permission to view users list"
    WRITE_USERS = "permission to create and edit users"
