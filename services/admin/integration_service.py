from flask_api import status
from sqlalchemy import case

from models.main import *
from models.appendix import *
from models.segment import *
from models.enums import RoleEnum
from services import permission_service

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


def update_integration_config(
    schema, status, nh_care, fl1, fl2, fl3, fl4, config, user
):
    if not permission_service.is_admin(user):
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    schema_config = (
        db.session.query(SchemaConfig).filter(SchemaConfig.schemaName == schema).first()
    )

    if schema_config == None:
        raise ValidationError(
            "Schema inválido",
            "errors.unauthorizedUser",
            status.HTTP_400_BAD_REQUEST,
        )

    schema_config.status = status if status != None else schema_config.status
    schema_config.nh_care = nh_care if nh_care != None else schema_config.nh_care
    schema_config.config = config if config != None else schema_config.config
    schema_config.fl1 = bool(fl1) if fl1 != None else schema_config.fl1
    schema_config.fl2 = bool(fl2) if fl2 != None else schema_config.fl2
    schema_config.fl3 = bool(fl3) if fl3 != None else schema_config.fl3
    schema_config.fl4 = bool(fl4) if fl4 != None else schema_config.fl4

    schema_config.updatedAt = datetime.today()
    schema_config.updatedBy = user.id

    db.session.flush()

    return _object_to_dto(schema_config)


def list_integrations(user):
    if not permission_service.is_admin(user):
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    integrations = (
        db.session.query(
            SchemaConfig,
            case([(SchemaConfig.schemaName == user.schema, 0)], else_=1).label(
                "priority"
            ),
        )
        .order_by("priority", SchemaConfig.schemaName)
        .all()
    )

    results = []
    for i in integrations:
        results.append(_object_to_dto(i[0]))

    return results


def _object_to_dto(schema_config: SchemaConfig):
    return {
        "schema": schema_config.schemaName,
        "status": schema_config.status,
        "nhCare": schema_config.nh_care,
        "config": schema_config.config,
        "fl1": schema_config.fl1,
        "fl2": schema_config.fl2,
        "fl3": schema_config.fl3,
        "fl4": schema_config.fl4,
    }
