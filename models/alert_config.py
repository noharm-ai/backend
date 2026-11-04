"""Section `alerts` of the schema params (models/schema_params.py).

Lenient models (unknown keys are ignored): admin validates on write. Every
default keeps the behaviour the system has without any config: the alert is
shown.
"""

from pydantic import BaseModel, ConfigDict, Field


class AlertTypeConfig(BaseModel):
    """Config of one alert type of alert_service (DrugAlertTypeEnum value)"""

    model_config = ConfigDict(extra="ignore")

    # off: the alert type is neither shown nor counted
    enabled: bool = True


_DEFAULT_TYPE_CONFIG = AlertTypeConfig()


class InteractionKindConfig(BaseModel):
    """Config of one interaction relation kind (it, dt, dm, iy, sl, rx)"""

    model_config = ConfigDict(extra="ignore")

    # hides the alert when either item's daily frequency (presmed.frequenciadia)
    # is in the list (e.g. FrequencyEnum.SN 33, FrequencyEnum.ACM 44); not
    # applied to rx, whose second side is an allergy
    ignoreFrequencies: list[float] = Field(default_factory=list)
    # iy only: shows the alert only when the items share an administration time
    requireIntervalIntersection: bool = False


_DEFAULT_KIND_CONFIG = InteractionKindConfig()


class AlertConfig(BaseModel):
    """Which alerts a schema shows"""

    model_config = ConfigDict(extra="ignore")

    # alert_service alerts, by type (DrugAlertTypeEnum value, e.g. "kidney")
    types: dict[str, AlertTypeConfig] = Field(default_factory=dict)
    # alert_interaction_service alerts, by relation kind
    interactions: dict[str, InteractionKindConfig] = Field(default_factory=dict)

    def alert_type(self, alert_type: str) -> AlertTypeConfig:
        """Config of an alert type (the defaults when it has none)"""
        return self.types.get(alert_type) or _DEFAULT_TYPE_CONFIG

    def interaction(self, kind: str) -> InteractionKindConfig:
        """Config of an interaction kind (the defaults when it has none)"""
        return self.interactions.get(kind) or _DEFAULT_KIND_CONFIG
