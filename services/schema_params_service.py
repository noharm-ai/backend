"""Service: the schema params kept in the DynamoDB noharm-store.

One item per schema (written by the admin project, only read here):
pk `schema_params`, sk `<schema>`, the config in `data`, one key per section
(models/schema_params.py). Whatever the item does not set comes from the
code defaults, which keep the behaviour the system has without any config.

Each section is validated on its own: an invalid one falls back to the code
defaults and the other sections still apply. When the table can't be read the
code defaults apply: a failure never changes behaviour (e.g. never hides an
alert).
"""

from flask import g, has_app_context
from pydantic import ValidationError as PydanticValidationError

from models.schema_params import SchemaParams
from repository import store_repository
from utils import logger

STORE_PK = "schema_params"
# section name -> its model, as declared in SchemaParams
_SECTIONS = {
    name: field.annotation for name, field in SchemaParams.model_fields.items()
}


def get_schema_params(schema: str | None) -> SchemaParams:
    """The schema params in force, read once per request"""
    cache = g.setdefault("schema_params", {}) if has_app_context() else {}
    if schema in cache:
        return cache[schema]

    config = _load(schema=schema)
    cache[schema] = config

    return config


def _load(schema: str | None) -> SchemaParams:
    """Reads the schema's item; the code defaults without one or when the table
    fails"""
    if not schema:
        return SchemaParams()

    try:
        items = store_repository.get_items_data(pk=STORE_PK, sks=[schema])
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.backend_logger.error(
            "schema params: noharm-store read failed (schema %s), using defaults: %s",
            schema,
            e,
        )
        return SchemaParams()

    if schema not in items:
        return SchemaParams()

    return SchemaParams(**_validated_sections(data=items[schema], schema=schema))


def _validated_sections(data, schema: str) -> dict:
    """The item's sections that validate; an invalid one is left out (its code
    defaults apply)"""
    if not isinstance(data, dict):
        logger.backend_logger.error(
            "schema params: item %s/%s ignored, data is not a map", STORE_PK, schema
        )
        return {}

    sections = {}
    for section, model in _SECTIONS.items():
        if section not in data:
            continue

        try:
            sections[section] = model.model_validate(data[section])
        except PydanticValidationError as e:
            logger.backend_logger.error(
                "schema params: section %s of %s/%s ignored: %s",
                section,
                STORE_PK,
                schema,
                e,
            )

    return sections
