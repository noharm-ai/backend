"""Module for defining permissions."""

from enum import Enum


class Permission(Enum):
    """Enum class for user permissions."""

    ADMIN_DRUGS = "ADMIN_DRUGS"  # "admin drug attributes"
    ADMIN_DRUGS__OVERWRITE_ATTRIBUTES = (
        "ADMIN_DRUGS__OVERWRITE_ATTRIBUTES"  # "permits overwriting attributes on copy"
    )

    ADMIN_EXAMS = "ADMIN_EXAMS"  # "admin exams"
    ADMIN_EXAMS__COPY = "ADMIN_EXAMS__COPY"  # "copy exams from other segments"
    ADMIN_EXAMS__MOST_FREQUENT = (
        "ADMIN_EXAMS__MOST_FREQUENT"  # "get most frequent exams"
    )

    ADMIN_FREQUENCIES = "ADMIN_FREQUENCIES"  # "admin frequency configs"
    ADMIN_ROUTES = "ADMIN_ROUTES"  # "admin routes configs"
    ADMIN_SUBSTANCE_RELATIONS = (
        "ADMIN_SUBSTANCE_RELATIONS"  # "admin substance relations"
    )
    ADMIN_SUBSTANCES = "ADMIN_SUBSTANCES"  # "admin substances"
    ADMIN_SEGMENTS = "ADMIN_SEGMENTS"  # "admin segments"
    ADMIN_UNIT_CONVERSION = "ADMIN_UNIT_CONVERSION"  # "admin unit conversions"
    ADMIN_UNIT = "ADMIN_UNIT"  # admin units

    ADMIN_PATIENT = "ADMIN_PATIENT"  # "admin extra patient configs"

    ADMIN_USERS = "ADMIN_USERS"  # "admin users"

    ADMIN_INTEGRATION_REMOTE = (
        "ADMIN_INTEGRATION_REMOTE"  # "grants integration remote access"
    )

    ADMIN_INTERVENTION_REASON = (
        "ADMIN_INTERVENTION_REASON"  # "admin intervention reason recordss"
    )

    ADMIN_NZERO = "ADMIN_NZERO"  # admin nzero config

    WRITE_SEGMENT_SCORE = "WRITE_SEGMENT_SCORE"  # "grant permission to generate score to the entire segment"

    INTEGRATION_UTILS = "INTEGRATION_UTILS"  # "grants permission to actions to help integration process"
    INTEGRATION_STATUS = (
        "INTEGRATION_STATUS"  # "grants access to view current integration status"
    )

    READ_REPORTS = "READ_REPORTS"  # "grants permission to view reports"

    READ_PRESCRIPTION = "READ_PRESCRIPTION"  # "view prescription"
    WRITE_PRESCRIPTION = "WRITE_PRESCRIPTION"  # "write prescription"

    WRITE_DRUG_ATTRIBUTES = (
        "WRITE_DRUG_ATTRIBUTES"  # "write permission on drug drug attributes"
    )
    WRITE_DRUG_SCORE = "WRITE_DRUG_SCORE"  # "write permission to generate/edit score"

    READ_BASIC_FEATURES = "READ_BASIC_FEATURES"  # "grants use of basic features"
    WRITE_BASIC_FEATURES = "WRITE_BASIC_FEATURES"  # "grants use of basic features"

    READ_DISCHARGE_SUMMARY = (
        "READ_DISCHARGE_SUMMARY"  # "grants access to discharge summary"
    )
    WRITE_DISCHARGE_SUMMARY = (
        "WRITE_DISCHARGE_SUMMARY"  # "grants access to discharge summary"
    )

    READ_SUPPORT = "READ_SUPPORT"  # "permission to view support tickets"
    WRITE_SUPPORT = "WRITE_SUPPORT"  # "permission to create support tickets"

    READ_USERS = "READ_USERS"  # "permission to view users list"
    WRITE_USERS = "WRITE_USERS"  # "permission to create and edit users"

    READ_DISPENSATION = "READ_DISPENSATION"  # "permission to view dispensation info"
    WRITE_DISPENSATION = (
        "WRITE_DISPENSATION"  # "permission to change dispensation info"
    )

    RUN_AS = "RUN_AS"  # "permission to service users"

    READ_STATIC = "READ_STATIC"  # "read static permission"
    CHECK_STATIC = "CHECK_STATIC"  # check from static context

    MULTI_SCHEMA = "MULTI_SCHEMA"  # "grants multi schema access"
    MAINTAINER = "MAINTAINER"  # "grants access to closed contracts"

    READ_REGULATION = "READ_REGULATION"  # grants access to read regulation data
    WRITE_REGULATION = "WRITE_REGULATION"  # grants access to write regulation data

    WRITE_TAGS = "WRITE_TAGS"  # permission to create and edit tags

    READ_PROTOCOLS = "READ_PROTOCOLS"  # permission to view protocols
    WRITE_PROTOCOLS = "WRITE_PROTOCOLS"  # permission to create and edit protocols
