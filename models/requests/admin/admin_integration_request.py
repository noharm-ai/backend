"""Request: admin integration related"""

from typing import Optional

from pydantic import BaseModel, IPvAnyAddress, IPvAnyNetwork


class AdminIntegrationCreateSchemaRequest(BaseModel):
    """Request: create new schema"""

    schema_name: str
    is_cpoe: bool
    is_pec: bool
    create_user: bool
    create_sqs: bool
    create_logstream: bool
    db_user: Optional[str] = None


class AdminIntegrationUpsertGetnameRequest(BaseModel):
    """Request: upsert getname"""

    schema_name: str
    ip: IPvAnyAddress


class AdminIntegrationUpsertSecurityGroupRequest(BaseModel):
    """Request: upsert security group"""

    schema_name: str
    rule_id: str = None
    sg_id: str = None
    new_cidr: IPvAnyNetwork
