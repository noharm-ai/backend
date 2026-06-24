"""Service: integration operations"""

from sqlalchemy import text

from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from models.appendix import InterventionReason
from models.main import User, db
from utils import status


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


@has_permission(Permission.ADMIN_INTERVENTION_REASON)
def init_intervention_reason(user_context: User):
    """init motivointervencao table with records from test schema"""
    schema = user_context.schema

    if db.session.query(InterventionReason).count() > 0:
        raise ValidationError(
            "A tabela motivointervencao já está preenchida",
            "errors.notSupported",
            status.HTTP_400_BAD_REQUEST,
        )

    insert = text(
        f"""
            insert into {schema}.motivointervencao
            (fkhospital, idmotivointervencao,nome, idmotivomae, ativo, suspensao, substituicao, tp_relacao, economia_customizada, bloqueante, ram)
            select fkhospital, idmotivointervencao,nome, idmotivomae, ativo, suspensao, substituicao, tp_relacao, economia_customizada, bloqueante, ram
            from hsc_test.motivointervencao
        """
    )

    reset_seq = text(
        f"""
            SELECT setval('{schema}.motivointervencao_idmotivointervencao_seq', (SELECT max(idmotivointervencao) + 1 from hsc_test.motivointervencao), true);
        """
    )

    db.session.execute(insert)
    return db.session.execute(reset_seq)
