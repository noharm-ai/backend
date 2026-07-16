"""Service: integration operations"""

import json

from sqlalchemy import text

from config import Config
from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from models.appendix import SchemaConfigAudit
from models.enums import SchemaConfigAuditTypeEnum
from models.main import User, db
from utils import aws, network_utils, status


def get_table_count(schema, table):
    """get estimated amount of record in a table"""

    query = text(
        """
        select
            n_live_tup as total_rows
        from
            pg_stat_user_tables
        where
            schemaname = :schemaname and relname = :table
        """
    )

    result = db.session.execute(query, {"schemaname": schema, "table": table})

    return ([row[0] for row in result])[0]


def _create_audit(
    schema: str, audit_type: SchemaConfigAuditTypeEnum, extra: dict, created_by: int
):
    from datetime import datetime

    audit = SchemaConfigAudit()
    audit.schemaName = schema
    audit.auditType = audit_type.value
    audit.extra = extra
    audit.createdAt = datetime.today()
    audit.createdBy = created_by
    db.session.add(audit)
    db.session.flush()


@has_permission(Permission.UPDATE_USER_SG)
def update_user_security_group(user_context: User):
    """Update user sg rules"""

    user = db.session.query(User).filter(User.id == user_context.id).first()

    remote_addr = network_utils.get_client_ip_with_validation()

    payload = {
        "command": "lambda_create_schema.update_user_sec_group_rules",
        "user": user.email,
        "new_cidr": remote_addr + "/32",
    }

    lambda_client = aws.get_client("lambda", region_name=Config.NIFI_SQS_QUEUE_REGION)
    response = lambda_client.invoke(
        FunctionName=Config.BACKEND_FUNCTION_NAME,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload),
    )

    response_json = json.loads(response["Payload"].read().decode("utf-8"))

    if isinstance(response_json, str):
        response_json = json.loads(response_json)

    if isinstance(response_json, dict) and response_json.get("error", False):
        raise ValidationError(
            response_json.get("message", "Erro inesperado. Consulte os logs"),
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    _create_audit(
        schema=user_context.schema,
        audit_type=SchemaConfigAuditTypeEnum.USER_SECURITY_GROUP,
        extra={"new_user_ip": remote_addr},
        created_by=user_context.id,
    )

    return response_json
