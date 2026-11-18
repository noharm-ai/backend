"""Repository: organizations (public.organizacao_schema). The access rules
built on them are in services/organization_service.py"""

from models.appendix import OrganizationSchema
from models.main import db


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

