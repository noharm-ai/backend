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
    MAP_SCHEDULES_FASTING = "map-schedules-fasting"
    MAP_SCHEDULES = "map-schedules"
    CUSTOM_FORMS = "custom-forms"


class GlobalMemoryEnum(Enum):
    SUMMARY_CONFIG = "summary-config"
    FEATURE_FLAGS = "feature-flags"


class NoHarmENV(Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class IntegrationStatusEnum(Enum):
    INTEGRATION = 0
    PRODUCTION = 1
    CANCELED = 2


class FeatureEnum(Enum):
    PRIMARY_CARE = "PRIMARYCARE"
    OAUTH = "OAUTH"
    LOCK_CHECKED_PRESCRIPTION = "LOCK_CHECKED_PRESCRIPTION"
    DISABLE_SOLUTION_TAB = "DISABLE_SOLUTION_TAB"
    PATIENT_REVISION = "PATIENT_REVISION"
    INTERVENTION_V2 = "INTERVENTION_V2"
    AUTHORIZATION_SEGMENT = "AUTHORIZATION_SEGMENT"
    CONCILIATION = "CONCILIATION"
    CONCILIATION_EDIT = "CONCILIATION_EDIT"
    DISABLE_CPOE = "DISABLE_CPOE"
    STAGING_ACCESS = "STAGING_ACCESS"
    AUTOMATIC_CHECK_IF_NOT_VALIDATED_ITENS = "AUTOMATIC_CHECK_IF_NOT_VALIDATED_ITENS"


class PrescriptionAuditTypeEnum(Enum):
    CHECK = 1
    UNCHECK = 2
    REVISION = 3
    UNDO_REVISION = 4
    INTEGRATION_CLINICAL_NOTES = 5
    INTEGRATION_PRESCRIPTION_RELEASE = 6
    UPSERT_CLINICAL_NOTES = 7
    CREATE_AGG = 8
    ERROR_INTEGRATION_PRESCRIPTION_RELEASE = 9


class PrescriptionDrugAuditTypeEnum(Enum):
    PROCESSED = 1
    UPSERT = 2
    INTEGRATION_PRESCRIPTION_DRUG_RELEASE = 3


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
    CUSTOM = 3


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


class NifiQueueActionTypeEnum(Enum):
    SET_STATE = "SET_STATE"
    REFRESH_STATE = "REFRESH_STATE"
    CLEAR_QUEUE = "CLEAR_QUEUE"
    LIST_QUEUE = "LIST_QUEUE"
    CLEAR_STATE = "CLEAR_STATE"
    TERMINATE_PROCESS = "TERMINATE_PROCESS"
    CUSTOM_CALLBACK = "CUSTOM_CALLBACK"
    REFRESH_TEMPLATE = "REFRESH_TEMPLATE"
    UPDATE_PROPERTY = "UPDATE_PROPERTY"


class DrugAlertTypeEnum(Enum):
    KIDNEY = "kidney"
    LIVER = "liver"
    PLATELETS = "platelets"
    ELDERLY = "elderly"
    TUBE = "tube"
    ALLERGY = "allergy"
    MAX_TIME = "maxTime"
    MAX_DOSE = "maxDose"
    MAX_DOSE_PLUS = "maxDosePlus"
    IRA = "ira"
    PREGNANT = "pregnant"
    LACTATING = "lactating"
    FASTING = "fasting"


class DrugAlertLevelEnum(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class DrugAttributesAuditTypeEnum(Enum):
    UPSERT = 1
    UPSERT_BEFORE_GEN_SCORE = 2
    UPSERT_UPDATE_SUBSTANCE = 3
    INSERT_FROM_REFERENCE = 4
    COPY_FROM_REFERENCE = 5


class PatientAuditTypeEnum(Enum):
    UPSERT = 1


class PatientConciliationStatusEnum(Enum):
    PENDING = 0
    CREATED = 1


class AppFeatureFlagEnum(Enum):
    REDIS_CACHE = "redisCache"
    REDIS_CACHE_EXAMS = "redisCacheExams"


class FrequencyEnum(Enum):
    SN = 33
    ACM = 44
    CONT = 55
    NOW = 66
    UNDEFINED = 99
