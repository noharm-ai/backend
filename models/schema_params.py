"""Schema params kept in the DynamoDB noharm-store (pk `schema_params`).

One item per schema (sk = the schema); whatever it does not set comes from the
code defaults. The config sits in the item's `data`, one key per section; each
section has its own model (e.g. models/alert_config.py) and is validated on its
own, so an invalid section never takes the others down.

Written by the admin project, which validates it strictly; here it is only
read, so the models are lenient (unknown keys and sections are ignored).
Every default keeps the behaviour the system has without any config.

To add a section: a model with defaults for every field, a field here, and the
same section in admin (the writer).
"""

from pydantic import BaseModel, ConfigDict, Field

from models.alert_config import AlertConfig


class SchemaParams(BaseModel):
    """The schema params in force (the schema's item over the code defaults)"""

    model_config = ConfigDict(extra="ignore")

    # which alerts are shown (models/alert_config.py)
    alerts: AlertConfig = Field(default_factory=AlertConfig)
