from flask_api import status

from models.main import *
from models.appendix import *
from models.segment import *
from models.enums import RoleEnum

from exception.validation_error import ValidationError


def get_table_count(schema, table):
    query = f"""
        select 
            n_live_tup as total_rows
        from
            pg_stat_user_tables 
        where 
            schemaname = :schemaname and relname = :table
    """

    result = db.session.execute(query, {"schemaname": schema, "table": table})

    return ([row[0] for row in result])[0]


def refresh_agg(user):
    roles = user.config["roles"] if user.config and "roles" in user.config else []
    if RoleEnum.ADMIN.value not in roles:
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )
    schema = user.schema
    max_table_count = 500000

    if get_table_count(schema, "prescricaoagg") > max_table_count:
        raise ValidationError(
            "A tabela possui muitos registros. A operação deve ser feita manualmente, fora do horário comercial.",
            "errors.notSupported",
            status.HTTP_400_BAD_REQUEST,
        )

    query = text(
        f"""
            insert into {schema}.prescricaoagg
            select * from {schema}.prescricaoagg
        """
    )

    return db.session.execute(query)
