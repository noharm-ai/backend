from enum import Enum


class MemoryEnum(Enum):
    PRESMED_FORM = "presmed-form"
    OAUTH_CONFIG = "oauth-config"
    OAUTH_KEYS = "oauth-keys"
    FEATURES = "features"
    ADMISSION_REPORTS = "admission-reports"
    REPORTS = "reports"
    GETNAME = "getnameurl"
    SUMMARY_CONFIG = "summary-config"


class NoHarmENV(Enum):
    STAGING = "staging"
    PRODUCTION = "production"


class RoleEnum(Enum):
    ADMIN = "admin"
    SUPPORT = "suporte"
    STAGING = "staging"
    TRAINING = "training"


class FeatureEnum(Enum):
    AUDIT = "AUDIT"
    PRIMARY_CARE = "PRIMARYCARE"
    OAUTH = "OAUTH"


class PrescriptionAuditTypeEnum(Enum):
    CHECK = 1
    UNCHECK = 2


class DrugTypeEnum(Enum):
    DRUG = "Medicamentos"
    SOLUTION = "Soluções"
    PROCEDURE = "Proced/Exames"
    DIET = "Dietas"
