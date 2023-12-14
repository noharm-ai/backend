from enum import Enum


class MemoryEnum(Enum):
    PRESMED_FORM = "presmed-form"
    OAUTH_CONFIG = "oauth-config"
    OAUTH_KEYS = "oauth-keys"
    FEATURES = "features"
    ADMISSION_REPORTS = "admission-reports"
    REPORTS = "reports"
    REPORTS_INTERNAL = "reports-internal"
    GETNAME = "getnameurl"
    SUMMARY_CONFIG = "summary-config"
    MAP_TUBE = "map-tube"
    MAP_IV = "map-iv"
    MAP_ROUTES = "map-routes"
    MAP_ORIGIN_DRUG = "map-origin-drug"
    MAP_ORIGIN_SOLUTION = "map-origin-solution"
    MAP_ORIGIN_PROCEDURE = "map-origin-procedure"
    MAP_ORIGIN_DIET = "map-origin-diet"
    MAP_ORIGIN_CUSTOM = "map-origin-custom"


class NoHarmENV(Enum):
    STAGING = "staging"
    PRODUCTION = "production"


class RoleEnum(Enum):
    ADMIN = "admin"
    SUPPORT = "suporte"
    STAGING = "staging"
    TRAINING = "training"
    DOCTOR = "doctor"
    READONLY = "readonly"
    MULTI_SCHEMA = "multi-schema"
    USER_ADMIN = "userAdmin"
    SUMMARY = "summary"


class FeatureEnum(Enum):
    PRIMARY_CARE = "PRIMARYCARE"
    OAUTH = "OAUTH"


class PrescriptionAuditTypeEnum(Enum):
    CHECK = 1
    UNCHECK = 2


class DrugAdminSegment(Enum):
    ADULT = 5
    KIDS = 7


class DrugTypeEnum(Enum):
    DRUG = "Medicamentos"
    SOLUTION = "Soluções"
    PROCEDURE = "Proced/Exames"
    DIET = "Dietas"


class ReportEnum(Enum):
    RPT_BIND = "report"
    RPT_PATIENT_DAY = "rpt_patient_day"
    RPT_PRESCRIPTION = "rpt_prescription"
    RPT_INTERVENTION = "rpt_intervention"
