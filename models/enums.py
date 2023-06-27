from enum import Enum


class MemoryEnum(Enum):
    PRESMED_FORM = "presmed-form"


class NoHarmENV(Enum):
    STAGING = "staging"
    PRODUCTION = "production"


class RoleEnum(Enum):
    SUPPORT = "suporte"


class FeatureEnum(Enum):
    AUDIT = "AUDIT"
    PRIMARY_CARE = "PRIMARYCARE"


class PrescriptionAuditTypeEnum(Enum):
    CHECK = 1
    UNCHECK = 2


class DrugTypeEnum(Enum):
    DRUG = "Medicamentos"
    SOLUTION = "Soluções"
    PROCEDURE = "Proced/Exames"
    DIET = "Dietas"
