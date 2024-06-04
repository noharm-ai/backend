from enum import Enum


class MemoryEnum(Enum):
    PRESMED_FORM = "presmed-form"
    OAUTH_CONFIG = "oauth-config"
    OAUTH_KEYS = "oauth-keys"
    FEATURES = "features"
    ADMISSION_REPORTS = "admission-reports"
    ADMISSION_REPORTS_INTERNAL = "admission-reports-internal"
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
    CUSTOM_FORMS = "custom-forms"


class GlobalMemoryEnum(Enum):
    SUMMARY_CONFIG = "summary-config"


class NoHarmENV(Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class IntegrationStatusEnum(Enum):
    INTEGRATION = 0
    PRODUCTION = 1
    CANCELED = 2


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
    UNLOCK_CHECKED_PRESCRIPTION = "unlock-checked-prescription"
    CPOE = "cpoe"


class FeatureEnum(Enum):
    PRIMARY_CARE = "PRIMARYCARE"
    OAUTH = "OAUTH"
    LOCK_CHECKED_PRESCRIPTION = "LOCK_CHECKED_PRESCRIPTION"
    DISABLE_SOLUTION_TAB = "DISABLE_SOLUTION_TAB"
    PATIENT_REVISION = "PATIENT_REVISION"
    INTERVENTION_V2 = "INTERVENTION_V2"


class PrescriptionAuditTypeEnum(Enum):
    CHECK = 1
    UNCHECK = 2
    REVISION = 3
    UNDO_REVISION = 4
    INTEGRATION_CLINICAL_NOTES = 5
    INTEGRATION_PRESCRIPTION_RELEASE = 6


class PrescriptionDrugAuditTypeEnum(Enum):
    PROCESSED = 1
    UPSERT = 2


class PrescriptionReviewTypeEnum(Enum):
    PENDING = 0
    REVIEWED = 1


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
    RPT_PATIENT_DAY = "PATIENT_DAY"
    RPT_PRESCRIPTION = "PRESCRIPTION"
    RPT_INTERVENTION = "INTERVENTION"
    RPT_PRESCRIPTION_AUDIT = "PRESCRIPTION_AUDIT"
    RPT_ECONOMY = "ECONOMY"


class InterventionEconomyTypeEnum(Enum):
    SUSPENSION = 1
    SUBSTITUTION = 2


class InterventionStatusEnum(Enum):
    PENDING = "s"
    REMOVED = "0"


class UserAuditTypeEnum(Enum):
    LOGIN = 1
    CREATE = 2
    UPDATE = 3
    FORGOT_PASSWORD = 4
    UPDATE_PASSWORD = 5
    REMOVE_CLINICAL_NOTE_ANNOTATION = 6
