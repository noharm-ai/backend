"""Section `alerts` of the schema params (models/schema_params.py).

Lenient models (unknown keys are ignored): admin validates on write. Every
default keeps the behaviour the system has without any config: the alert is
shown, as it is calculated today.
"""

from pydantic import BaseModel, ConfigDict, Field, field_validator

from models.enums import DrugAlertLevelEnum

_ALERT_LEVELS = {level.value for level in DrugAlertLevelEnum}


class AlertTypeConfig(BaseModel):
    """Config of one alert type of alert_service (DrugAlertTypeEnum value)"""

    model_config = ConfigDict(extra="ignore")

    # off: the alert type is neither shown nor counted
    enabled: bool = True
    # low | medium | high: replaces the level the alert sets (also when it varies
    # within the type, e.g. pregnant D/X); None keeps it. Not applied to
    # protocol, whose level each protocol sets
    level: str | None = None

    @field_validator("level", mode="before")
    @classmethod
    def _known_level(cls, level):
        """An unknown level keeps the alert's own (never invalidates the section)"""
        return level if level in _ALERT_LEVELS else None


DEFAULT_KIDNEY_ADULT_EXAMS = ["ckd21", "ckd"]
DEFAULT_KIDNEY_PEDIATRIC_EXAMS = ["swrtz2", "swrtz1"]


class KidneyAlertConfig(AlertTypeConfig):
    """Kidney alert: which renal function exams (tpexam, in order) are compared
    with the drug's kidney limit (alert_service._alert_kidney)"""

    # patient over 17: the first exam with a value decides
    adultExams: list[str] = Field(
        default_factory=lambda: list(DEFAULT_KIDNEY_ADULT_EXAMS)
    )
    # patient up to 17: the first exam below the limit raises the alert
    pediatricExams: list[str] = Field(
        default_factory=lambda: list(DEFAULT_KIDNEY_PEDIATRIC_EXAMS)
    )

    @field_validator("adultExams", "pediatricExams", mode="after")
    @classmethod
    def _normalize_exams(cls, exams: list[str], info) -> list[str]:
        """tpexam as the exams are keyed (lower case); an empty list keeps the
        defaults, so the alert never loses its exams"""
        normalized = [e.strip().lower() for e in exams if e and e.strip()]
        if normalized:
            return list(dict.fromkeys(normalized))

        if info.field_name == "adultExams":
            return list(DEFAULT_KIDNEY_ADULT_EXAMS)

        return list(DEFAULT_KIDNEY_PEDIATRIC_EXAMS)


def _type_field():
    return Field(default_factory=AlertTypeConfig)


class AlertTypesConfig(BaseModel):
    """One entry per alert_service alert type (DrugAlertTypeEnum values); a type
    with options of its own has its own model (e.g. kidney)"""

    model_config = ConfigDict(extra="ignore")

    kidney: KidneyAlertConfig = Field(default_factory=KidneyAlertConfig)
    liver: AlertTypeConfig = _type_field()
    platelets: AlertTypeConfig = _type_field()
    elderly: AlertTypeConfig = _type_field()
    tube: AlertTypeConfig = _type_field()
    allergy: AlertTypeConfig = _type_field()
    maxTime: AlertTypeConfig = _type_field()
    maxDose: AlertTypeConfig = _type_field()
    maxDosePlus: AlertTypeConfig = _type_field()
    ira: AlertTypeConfig = _type_field()
    pregnant: AlertTypeConfig = _type_field()
    lactating: AlertTypeConfig = _type_field()
    fasting: AlertTypeConfig = _type_field()
    protocol: AlertTypeConfig = _type_field()
    cultureResistant: AlertTypeConfig = _type_field()
    cultureResistantClass: AlertTypeConfig = _type_field()


_DEFAULT_TYPE_CONFIG = AlertTypeConfig()


class InteractionKindConfig(BaseModel):
    """Config of one interaction relation kind (it, dt, dm, iy, sl, rx)"""

    model_config = ConfigDict(extra="ignore")

    # off: the kind is neither shown nor counted
    enabled: bool = True
    # hides the alert when either item's daily frequency (presmed.frequenciadia)
    # is in the list (e.g. FrequencyEnum.SN 33, FrequencyEnum.ACM 44); not
    # applied to rx, whose second side is an allergy
    ignoreFrequencies: list[float] = Field(default_factory=list)
    # shows the alert only when the items share an administration time; not
    # applied to rx, whose second side is an allergy
    requireIntervalIntersection: bool = False


_DEFAULT_KIND_CONFIG = InteractionKindConfig()


class AlertConfig(BaseModel):
    """Which alerts a schema shows"""

    model_config = ConfigDict(extra="ignore")

    # alert_service alerts, by type (DrugAlertTypeEnum value, e.g. "kidney")
    types: AlertTypesConfig = Field(default_factory=AlertTypesConfig)
    # alert_interaction_service alerts, by relation kind
    interactions: dict[str, InteractionKindConfig] = Field(default_factory=dict)

    def alert_type(self, alert_type: str) -> AlertTypeConfig:
        """Config of an alert type (the defaults for a type it does not know)"""
        if alert_type not in AlertTypesConfig.model_fields:
            return _DEFAULT_TYPE_CONFIG

        return getattr(self.types, alert_type)

    def interaction(self, kind: str) -> InteractionKindConfig:
        """Config of an interaction kind (the defaults when it has none)"""
        return self.interactions.get(kind) or _DEFAULT_KIND_CONFIG
