from enum import Enum


class MemoryEnum(Enum):
    PRESMED_FORM = "presmed-form"


class NoHarmENV(Enum):
    STAGING = "staging"
    PRODUCTION = "production"
