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

from decorators.has_permission_decorator import Permission, has_permission
from models.main import User
from models.schema_params import SchemaParams
from repository import store_repository
from utils import logger

STORE_PK = "schema_params"
# section name -> its model, as declared in SchemaParams
_SECTIONS = {
    name: field.annotation for name, field in SchemaParams.model_fields.items()
}


@has_permission(Permission.MAINTAINER)
def view_schema_params(user_context: User = None) -> dict:
    """The schema params of the user's schema, for maintainers (read only: the
    admin project edits them). `params` is what is in force (code defaults
    filled in), `custom` only what the schema's item sets"""
    loaded = _load_with_status(schema=user_context.schema)

    return {
        "schema": user_context.schema,
        "status": loaded["status"],
        "invalidSections": loaded["invalidSections"],
        "params": loaded["params"].model_dump(),
        "custom": loaded["params"].model_dump(exclude_unset=True),
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
    return _load_with_status(schema=schema)["params"]


def _load_with_status(schema: str | None) -> dict:
    """The params in force and how they were read: status `found`, `not_found`
    (no item: code defaults), `read_error` (the table failed: code defaults) or
    `no_schema`; invalidSections lists the sections of the item left out"""
    result = {"params": SchemaParams(), "status": "no_schema", "invalidSections": []}
    if not schema:
        return result

    try:
        data = store_repository.get_item_data(pk=STORE_PK, sk=schema)
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.backend_logger.error(
            "schema params: noharm-store read failed (schema %s), using defaults: %s",
            schema,
            e,
        )
        result["status"] = "read_error"
        return result

    if data is None:
        result["status"] = "not_found"
        return result

    invalid = []
    result["params"] = SchemaParams(
        **_validated_sections(data=data, schema=schema, invalid=invalid)
    )
    result["status"] = "found"
    result["invalidSections"] = invalid

    return result


def _validated_sections(data, schema: str, invalid: list | None = None) -> dict:
    """The item's sections that validate; an invalid one is left out (its code
    defaults apply) and named in `invalid`, when given"""
    invalid = invalid if invalid is not None else []

    if not isinstance(data, dict):
        logger.backend_logger.error(
            "schema params: item %s/%s ignored, data is not a map", STORE_PK, schema
        )
        invalid.append("data")
        return {}

    sections = {}
    for section, model in _SECTIONS.items():
        if section not in data:
            continue

        # any error, not only pydantic's: a bad value never breaks the view
        try:
            sections[section] = model.model_validate(data[section])
        except Exception as e:  # pylint: disable=broad-exception-caught
            invalid.append(section)
            logger.backend_logger.error(
                "schema params: section %s of %s/%s ignored: %s",
                section,
                STORE_PK,
                schema,
                e,
            )

    return sections
