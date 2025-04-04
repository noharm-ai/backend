import json
from utils import status
from sqlalchemy import case, text
from datetime import datetime

from models.main import db, User
from models.appendix import SchemaConfig, InterventionReason
from decorators.has_permission_decorator import has_permission, Permission

from exception.validation_error import ValidationError


def get_table_count(schema, table):
    query = text(
        f"""
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


def can_refresh_agg(schema):
    max_table_count = 300000

    return get_table_count(schema, "prescricaoagg") <= max_table_count


@has_permission(Permission.WRITE_SEGMENT_SCORE)
def refresh_agg(user_context: User):
    schema = user_context.schema

    if not can_refresh_agg(user_context.schema):
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


@has_permission(Permission.INTEGRATION_UTILS)
def refresh_prescriptions(user_context: User):
    schema = user_context.schema
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


@has_permission(Permission.ADMIN_INTERVENTION_REASON)
def init_intervention_reason(user_context: User):
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
            (fkhospital, idmotivointervencao,nome, idmotivomae, ativo, suspensao, substituicao, tp_relacao, economia_customizada)
            select fkhospital, idmotivointervencao,nome, idmotivomae, ativo, suspensao, substituicao, tp_relacao, economia_customizada
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


@has_permission(Permission.INTEGRATION_UTILS)
def update_integration_config(
    schema, status, nh_care, fl1, fl2, fl3, fl4, config, user_context: User, cpoe: bool
):
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
    schema_config.config = _set_new_config(
        old_config=schema_config.config if schema_config.config else {},
        new_config=config,
    )
    schema_config.fl1 = bool(fl1) if fl1 != None else schema_config.fl1
    schema_config.fl2 = bool(fl2) if fl2 != None else schema_config.fl2
    schema_config.fl3 = bool(fl3) if fl3 != None else schema_config.fl3
    schema_config.fl4 = bool(fl4) if fl4 != None else schema_config.fl4
    schema_config.cpoe = cpoe

    schema_config.updatedAt = datetime.today()
    schema_config.updatedBy = user_context.id

    db.session.flush()

    schema_config_db = (
        db.session.query(SchemaConfig).filter(SchemaConfig.schemaName == schema).first()
    )

    return _object_to_dto(schema_config_db)


def _set_new_config(old_config: dict, new_config: dict):
    config = dict({}, **old_config)

    if "getname" in new_config:
        config["getname"] = {"type": new_config["getname"]["type"]}

        if "auth" == config["getname"]["type"]:
            config["getname"]["secret"] = new_config["getname"]["secret"]
        elif "proxy" == config["getname"]["type"]:
            config["getname"]["url"] = new_config["getname"]["url"]
            config["getname"]["urlDev"] = new_config["getname"].get("urlDev", None)
            config["getname"]["params"] = new_config["getname"]["params"]
            config["getname"]["internal"] = new_config["getname"].get("internal", False)
            config["getname"]["authPrefix"] = new_config["getname"].get(
                "authPrefix", ""
            )
            config["getname"]["token"] = {
                "url": new_config["getname"]["token"]["url"],
                "params": new_config["getname"]["token"]["params"],
            }

    if "remotenifi" in new_config:
        main_schema = new_config["remotenifi"].get("main", None)
        config["remotenifi"] = {"main": main_schema if main_schema != "" else None}

    return config


@has_permission(Permission.INTEGRATION_UTILS)
def list_integrations(user_context: User):
    integrations = (
        db.session.query(
            SchemaConfig,
            case((SchemaConfig.schemaName == user_context.schema, 0), else_=1).label(
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
        "cpoe": schema_config.cpoe,
    }
