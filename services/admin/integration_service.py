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


def can_refresh_agg(schema):
    max_table_count = 500000

    return get_table_count(schema, "prescricaoagg") <= max_table_count


def refresh_agg(user):
    roles = user.config["roles"] if user.config and "roles" in user.config else []
    if RoleEnum.ADMIN.value not in roles and RoleEnum.TRAINING.value not in roles:
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )
    schema = user.schema

    if not can_refresh_agg(user.schema):
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


def refresh_prescriptions(user):
    roles = user.config["roles"] if user.config and "roles" in user.config else []
    if RoleEnum.ADMIN.value not in roles:
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )
    schema = user.schema
    max_table_count = 100000

    if get_table_count(schema, "prescricao") > max_table_count:
        raise ValidationError(
            "A tabela possui muitos registros. A operação deve ser feita manualmente, fora do horário comercial.",
            "errors.notSupported",
            status.HTTP_400_BAD_REQUEST,
        )

    queryPrescription = text(
        f"""
            insert into {schema}.prescricao
            select * from {schema}.prescricao
        """
    )

    queryPresmed = text(
        f"""
            insert into {schema}.presmed
            select * from {schema}.presmed
        """
    )

    db.session.execute(queryPrescription)
    return db.session.execute(queryPresmed)


def init_intervention_reason(user):
    roles = user.config["roles"] if user.config and "roles" in user.config else []
    if RoleEnum.ADMIN.value not in roles and RoleEnum.TRAINING.value not in roles:
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    schema = user.schema

    if db.session.query(InterventionReason).count() > 0:
        raise ValidationError(
            "A tabela motivointervencao já está preenchida",
            "errors.notSupported",
            status.HTTP_400_BAD_REQUEST,
        )

    insert = text(
        f"""
            insert into {schema}.motivointervencao
            (fkhospital, idmotivointervencao,nome, idmotivomae, ativo, suspensao, substituicao, tp_relacao)
            select fkhospital, idmotivointervencao,nome, idmotivomae, ativo, suspensao, substituicao, tp_relacao
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
