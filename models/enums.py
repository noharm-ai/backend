from enum import Enum


class MemoryEnum(Enum):
    PRESMED_FORM = "presmed-form"
    OAUTH_CONFIG = "oauth-config"
    FEATURES = "features"


class FeatureEnum(Enum):
    OAUTH = "OAUTH"


class NoHarmENV(Enum):
    STAGING = "staging"
    PRODUCTION = "production"
