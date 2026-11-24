"""Service: infection control mode of the schema (full or lite)

FULL (the INFECTION_CONTROL feature) is the follow-up with reasons, reviews and
the worklist. LITE (the INFECTION_CONTROL_LITE feature alone) keeps only what
the report's DOT/LOT needs: prescalc follows the admissions (revised, without
reasons) and the nightly run of backend-private keeps their summary.
"""

from models.enums import FeatureEnum, InfectionControlModeEnum
from services import feature_service


def get_mode() -> InfectionControlModeEnum | None:
    """The schema's infection control mode from its features (FULL wins over
    LITE), None when neither is on"""
    if feature_service.has_feature(FeatureEnum.INFECTION_CONTROL):
        return InfectionControlModeEnum.FULL

    if feature_service.has_feature(FeatureEnum.INFECTION_CONTROL_LITE):
        return InfectionControlModeEnum.LITE

    return None
