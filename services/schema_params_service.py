"""Service: the schema params kept in the schema's `memoria`.

One record per schema (written by the admin project, only read here): `tipo`
`schema-params` (MemoryEnum.SCHEMA_PARAMS), the config in `valor`, one key per
section (models/schema_params.py). No record means the code defaults, which
keep the behaviour the system has without any config. The kind is an admin
memory (memory_service.is_admin_memory): no user of this project can write it.

The prescription view reads the record with the other memory records it loads
(_get_configs), so the params cost no query of their own and a change made in
admin applies on the next view.

Each section is validated on its own: an invalid one falls back to the code
defaults and the other sections still apply.
"""

from decorators.has_permission_decorator import Permission, has_permission
from models.enums import MemoryEnum
from models.main import User
from models.schema_params import SchemaParams
from services import memory_service
from utils import logger

KIND = MemoryEnum.SCHEMA_PARAMS.value

# section name -> its model, as declared in SchemaParams
_SECTIONS = {
    name: field.annotation for name, field in SchemaParams.model_fields.items()
}


@has_permission(Permission.MAINTAINER)
def view_schema_params(user_context: User = None) -> dict:
    """The schema params of the user's schema, for maintainers (read only: the
    admin project edits them). `params` is what is in force (code defaults
    filled in), `custom` only what the schema's record sets"""
    record = memory_service.get_memory(KIND)
    loaded = _load_with_status(
        value=record.value if record is not None else None,
        found=record is not None,
        schema=user_context.schema,
    )

    return {
        "schema": user_context.schema,
        "status": loaded["status"],
        "invalidSections": loaded["invalidSections"],
        "params": loaded["params"].model_dump(),
        "custom": loaded["params"].model_dump(exclude_unset=True),
    }


def from_memory(memory_itens: dict, schema: str | None = None) -> SchemaParams:
    """The schema params in force, from the memory records already read (by
    kind, as memory_service.get_by_kind gives them): the code defaults when
    the schema has no record"""
    return _load_with_status(
        value=memory_itens.get(KIND),
        found=KIND in memory_itens,
        schema=schema,
    )["params"]


def _load_with_status(value, found: bool, schema: str | None) -> dict:
    """The params in force and how they were read: status `found` or
    `not_found` (no record: code defaults); invalidSections lists the sections
    of the record left out"""
    if not found:
        return {"params": SchemaParams(), "status": "not_found", "invalidSections": []}

    invalid = []
    params = SchemaParams(
        **_validated_sections(data=value, schema=schema, invalid=invalid)
    )

    return {"params": params, "status": "found", "invalidSections": invalid}


def _validated_sections(data, schema: str | None, invalid: list | None = None) -> dict:
    """The record's sections that validate; an invalid one is left out (its
    code defaults apply) and named in `invalid`, when given"""
    invalid = invalid if invalid is not None else []

    if not isinstance(data, dict):
        logger.backend_logger.error(
            "schema params: record of %s ignored, its value is not a map", schema
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
                "schema params: section %s of %s ignored: %s",
                section,
                schema,
                e,
            )

    return sections
