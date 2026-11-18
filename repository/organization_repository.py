"""Repository: organizations (public.organizacao_schema) and the schemas
usuario_extra grants through them"""

from models.appendix import OrganizationSchema
from models.main import db
from security.role import Role


def get_organization_schemas(id_organization: int) -> list[dict]:
    """The schemas of an organization, as usuario_extra.config['schemas'] entries.

    No join to schema_config: organizacao_schema references it ON DELETE
    CASCADE, so a removed schema leaves the organization with it
    """
    rows = (
        db.session.query(OrganizationSchema)
        .filter(OrganizationSchema.idOrganization == id_organization)
        .order_by(OrganizationSchema.name, OrganizationSchema.schemaName)
        .all()
    )
    return [{"name": row.schemaName, "friendlyName": row.name} for row in rows]


def get_organization_grant(config) -> dict | None:
    """usuario_extra.config['organization'] as {"id": int, "allSchemas": bool},
    or None when absent, malformed or the config lacks ORGANIZATION_MANAGER
    (a NAVIGATOR, or a former manager, keeps only the fixed list).

    user_repository.get_extra_schema_users_list applies the same rules in SQL:
    keep both in step
    """
    if not isinstance(config, dict):
        return None
    roles = config.get("roles")
    if not isinstance(roles, list) or Role.ORGANIZATION_MANAGER.value not in roles:
        return None
    raw = config.get("organization")
    if not isinstance(raw, dict):
        return None
    raw_id = raw.get("id")
    if isinstance(raw_id, bool) or not isinstance(raw_id, int):
        return None
    return {"id": raw_id, "allSchemas": raw.get("allSchemas") is True}


def get_extra_schemas(config) -> list[dict]:
    """The schemas a usuario_extra.config grants.

    The fixed list in config['schemas'], plus, when the user manages every
    schema of an organization (config['organization']['allSchemas']), the
    organization's current schemas: a schema added to the organization later
    is reached without touching the user.
    """
    if not isinstance(config, dict):
        return []
    schemas = config.get("schemas", [])
    schemas = list(schemas) if isinstance(schemas, list) else []

    grant = get_organization_grant(config)
    if grant is None or not grant["allSchemas"]:
        return schemas

    names = {s.get("name") for s in schemas if isinstance(s, dict)}
    for schema in get_organization_schemas(grant["id"]):
        if schema["name"] not in names:
            schemas.append(schema)
            names.add(schema["name"])
    return schemas
