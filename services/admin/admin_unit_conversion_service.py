import json
from datetime import datetime

import boto3
import requests
from markupsafe import escape as escape_html
from sqlalchemy import text

from config import Config
from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from models.enums import DefaultMeasureUnitEnum
from models.main import (
    DrugAttributes,
    User,
    db,
)
from models.segment import Segment
from repository import unit_conversion_repository
from services import drug_service as main_drug_service
from services.admin import (
    admin_drug_service,
)
from utils import status


@has_permission(Permission.ADMIN_UNIT_CONVERSION)
def get_conversion_predictions(conversion_list: list) -> list:
    to_infer = []
    for index, conversion_item in enumerate(conversion_list):
        destiny_unit = (
            conversion_item.get("substanceMeasureUnit", DefaultMeasureUnitEnum.MG.value)
            if conversion_item.get("substanceMeasureUnit", None)
            else DefaultMeasureUnitEnum.MG.value
        )

        if conversion_item.get("prediction", None) is None:
            # Sanitize user input to prevent XSS
            name = conversion_item.get("name")
            sctid = conversion_item.get("sctid")

            to_infer.append(
                {
                    "id": index,
                    "nome": escape_html(str(name)) if name is not None else None,
                    "unidade_noharm": destiny_unit,
                    "fkunidademedida": conversion_item.get("idMeasureUnit"),
                    "sctid": escape_html(str(sctid)) if sctid is not None else None,
                }
            )

    if to_infer:
        if not Config.SERVICE_INFERENCE:
            raise ValueError("SERVICE_INFERENCE not set")

        try:
            response = requests.post(
                f"{Config.SERVICE_INFERENCE}conversion-units/infer",
                json={"conversion_unit_list": to_infer},
                timeout=25,
            )
            response.raise_for_status()
        except requests.exceptions.RequestException:
            raise ValidationError(
                "Serviço de inferência indisponível",
                "errors.serviceUnavailable",
                status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        response_object = response.json()

        for item in response_object:
            try:
                if item.get("probability", 0) < 80:
                    conversion_list[item.get("id")]["prediction"] = "Curadoria"
                else:
                    conversion_list[item.get("id")]["prediction"] = float(
                        item.get("prediction")
                    )
            except ValueError:
                conversion_list[item.get("id")]["prediction"] = "Curadoria"

            conversion_list[item.get("id")]["probability"] = item.get("probability")

    return conversion_list


@has_permission(Permission.ADMIN_UNIT_CONVERSION)
def get_conversion_list(id_segment):
    unit_conversion_repository.ensure_default_measure_units()

    nh_default_units = [
        DefaultMeasureUnitEnum.MCG.value,
        DefaultMeasureUnitEnum.MG.value,
        DefaultMeasureUnitEnum.ML.value,
        DefaultMeasureUnitEnum.UI.value,
        DefaultMeasureUnitEnum.UN.value,
    ]

    default_units = {}
    for du in nh_default_units:
        default_units[du] = {
            "idMeasureUnit": du,
            "description": du,
            "measureunit_nh": du,
        }

    conversion_list = unit_conversion_repository.get_unit_conversion_list()

    result = []
    drug_defaultunit = set()
    for i in conversion_list:
        prediction = None
        probability = None

        show_factors = True

        if not i.uniform_measure_unit:
            show_factors = False

        effective_default = i.default_measureunit or DefaultMeasureUnitEnum.UN.value
        is_default_unit = effective_default == i.measureunit_nh

        if is_default_unit:
            factor = 1
            prediction = 100
            probability = 100
        elif show_factors:
            factor = i.factor
            prediction = None
            probability = None
        else:
            factor = None
            prediction = None
            probability = None

        if i.idMeasureUnit == effective_default:
            drug_defaultunit.add(i.id)

        result.append(
            {
                "id": f"{i.id}-{i.idMeasureUnit}",
                "idDrug": i[1],
                "name": escape_html(str(i[2])) if i[2] is not None else None,
                "idMeasureUnit": i[3],
                "factor": factor,
                "measureUnit": escape_html(str(i[5])) if i[5] is not None else None,
                "sctid": escape_html(str(i.sctid)) if i.sctid is not None else None,
                "substanceMeasureUnit": effective_default,
                "drugMeasureUnitNh": i.measureunit_nh,
                "prediction": prediction,
                "probability": probability,
                "prescribedQuantity": i.prescribed_quantity,
                "substanceTags": i.tags,
                "uniformMeasureUnit": i.uniform_measure_unit,
                "substanceName": i.substance_name,
            }
        )

    for i in conversion_list:
        effective_default = i.default_measureunit or DefaultMeasureUnitEnum.UN.value
        if i.id not in drug_defaultunit:
            drug_defaultunit.add(i.id)

            d_unit = default_units.get(effective_default, None)

            if d_unit:
                result.append(
                    {
                        "id": f"{i.id}-{d_unit.get('idMeasureUnit')}",
                        "idDrug": i.id,
                        "name": escape_html(str(i.name))
                        if i.name is not None
                        else None,
                        "idMeasureUnit": d_unit.get("idMeasureUnit"),
                        "factor": 1,
                        "measureUnit": escape_html(str(d_unit.get("description")))
                        if d_unit.get("description") is not None
                        else None,
                        "sctid": escape_html(str(i.sctid))
                        if i.sctid is not None
                        else None,
                        "substanceMeasureUnit": i.default_measureunit
                        if i.default_measureunit
                        else DefaultMeasureUnitEnum.UN.value,
                        "drugMeasureUnitNh": d_unit.get("measureunit_nh", None),
                        "prediction": 1,
                        "probability": 100,
                        "prescribed_quantity": i.prescribed_quantity,
                        "substanceTags": i.tags,
                        "uniformMeasureUnit": i.uniform_measure_unit,
                        "substanceName": i.substance_name,
                    }
                )

    grouped_result = {}
    for item in result:
        id_drug = item["idDrug"]
        if id_drug not in grouped_result:
            grouped_result[id_drug] = []
        grouped_result[id_drug].append(item)

    grouped_result = {
        id_drug: items
        for id_drug, items in grouped_result.items()
        if all(i["substanceMeasureUnit"] == i["drugMeasureUnitNh"] for i in items)
    }

    for group in grouped_result.values():
        print("id_drug", group[0]["idDrug"])
        for item in group:
            print(item["name"])
        print("--- ---")

    return grouped_result


@has_permission(Permission.ADMIN_UNIT_CONVERSION)
def save_conversions(
    id_drug,
    id_segment,
    id_measure_unit_default,
    conversion_list,
    user_context: User,
    wait_for_lambda: bool = False,
    skip_lambda: bool = False,
):
    if (
        id_drug == None
        or id_segment == None
        or id_measure_unit_default == None
        or conversion_list == None
        or len(conversion_list) == 0
    ):
        raise ValidationError(
            "Parâmetros inválidos",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )

    for uc in conversion_list:
        try:
            factor = float(uc["factor"]) if uc["factor"] is not None else None
            uc["factor"] = factor
        except (ValueError, TypeError):
            raise ValidationError(
                "Fator de conversão deve ser um número válido",
                "errors.invalidParams",
                status.HTTP_400_BAD_REQUEST,
            )

        if uc["factor"] is None or uc["factor"] == 0:
            raise ValidationError(
                "Fator de conversão inválido",
                "errors.invalidParams",
                status.HTTP_400_BAD_REQUEST,
            )

    # update all segments
    updated_segments = []
    segments = db.session.query(Segment).all()

    for s in segments:
        updated_segments.append(s.description)

        # set drug attributes
        da = (
            db.session.query(DrugAttributes)
            .filter(DrugAttributes.idDrug == id_drug)
            .filter(DrugAttributes.idSegment == s.id)
            .first()
        )

        if da is None:
            da = main_drug_service.create_attributes_from_reference(
                id_drug=id_drug, id_segment=s.id, user=user_context
            )

        da.idMeasureUnit = id_measure_unit_default
        da.update = datetime.today()
        da.user = user_context.id

        db.session.flush()

        # update conversions
        _update_conversion_list(
            conversion_list=conversion_list,
            id_drug=id_drug,
            id_segment=s.id,
            user=user_context,
        )

        admin_drug_service.calculate_dosemax_uniq(id_drug=id_drug, id_segment=s.id)

    # call lambda to generate scores
    if skip_lambda:
        return {"updated": updated_segments}

    lambda_client = boto3.client("lambda", region_name=Config.NIFI_SQS_QUEUE_REGION)
    lambda_response = lambda_client.invoke(
        FunctionName=Config.BACKEND_FUNCTION_NAME,
        InvocationType="RequestResponse" if wait_for_lambda else "Event",
        Payload=json.dumps(
            {
                "command": "lambda_scores.process_drug_scores",
                "schema": user_context.schema,
                "id_user": user_context.id,
                "id_drug": id_drug,
            }
        ),
    )

    result = {"updated": updated_segments}

    if wait_for_lambda:
        payload = lambda_response.get("Payload")
        result["lambdaResponse"] = json.loads(payload.read()) if payload else None

    return result


def _update_conversion_list(conversion_list, id_drug, id_segment, user):
    for uc in conversion_list:
        insert_units = text(
            f"""
            insert into {user.schema}.unidadeconverte
                (idsegmento, fkmedicamento, fkunidademedida, fator)
            values
                (:id_segment, :id_drug, :id_measure_unit, :factor)
            on conflict (idsegmento, fkmedicamento, fkunidademedida)
            do update set fator = :factor
        """
        )

        db.session.execute(
            insert_units,
            {
                "id_segment": id_segment,
                "id_drug": id_drug,
                "id_measure_unit": uc["idMeasureUnit"],
                "factor": uc["factor"],
            },
        )


@has_permission(Permission.ADMIN_UNIT_CONVERSION)
def add_default_units(user_context: User):
    schema = user_context.schema

    admin_drug_service.fix_inconsistency()

    query = text(
        f"""
        with unidades as (
            select
                fkmedicamento, min(fkunidademedida) as fkunidademedida
            from (
                select
                    fkmedicamento, fkunidademedida
                from {schema}.prescricaoagg p
                where
                    p.fkunidademedida is not null
                    and p.fkunidademedida <> ''
                    and p.fkmedicamento in (
                        select fkmedicamento from {schema}.medatributos m where m.fkunidademedida is null
                    )
                group by fkmedicamento, fkunidademedida
            ) a
            group by fkmedicamento
            having count(*) = 1
        ), unidades_segmento as (
            select fkmedicamento, fkunidademedida, s.idsegmento  from unidades, {schema}.segmento s
        )
        update
            {schema}.medatributos ma
        set
            fkunidademedida = unidades_segmento.fkunidademedida
        from
            unidades_segmento
        where
            ma.fkmedicamento = unidades_segmento.fkmedicamento
            and ma.idsegmento = unidades_segmento.idsegmento
            and ma.fkunidademedida is null
    """
    )

    insert_units = text(
        f"""
        insert into {schema}.unidadeconverte
            (idsegmento, fkmedicamento, fkunidademedida, fator)
        select
            m.idsegmento, m.fkmedicamento, m.fkunidademedida, 1
        from
            {schema}.medatributos m
        where
            m.fkunidademedida is not null
            and m.fkunidademedida != ''
        on conflict (idsegmento, fkmedicamento, fkunidademedida)
        do nothing
    """
    )

    result = db.session.execute(query)

    db.session.execute(insert_units)

    return result


@has_permission(Permission.ADMIN_UNIT_CONVERSION)
def copy_unit_conversion(id_segment_origin, id_segment_destiny, user_context: User):
    schema = user_context.schema

    if id_segment_origin == None or id_segment_destiny == None:
        raise ValidationError(
            "Segmento Inválido", "errors.invalidRecord", status.HTTP_400_BAD_REQUEST
        )

    if id_segment_origin == id_segment_destiny:
        raise ValidationError(
            "Segmento origem deve ser diferente do segmento destino",
            "errors.invalidRecord",
            status.HTTP_400_BAD_REQUEST,
        )

    query = text(
        f"""
        with conversao_origem as (
            select
                ma.fkmedicamento, ma.idsegmento, ma.fkunidademedida
            from
                {schema}.medatributos ma
                inner join {schema}.medatributos madestino on (
                    ma.fkmedicamento = madestino.fkmedicamento
                    and madestino.idsegmento  = :idSegmentDestiny
                    and ma.fkunidademedida = madestino.fkunidademedida
                )
            where
                ma.idsegmento = :idSegmentOrigin
        )
        insert into {schema}.unidadeconverte (idsegmento, fkunidademedida, fator, fkmedicamento) (
            select
                :idSegmentDestiny as idsegmento,
                u.fkunidademedida,
                u.fator,
                u.fkmedicamento
            from
                {schema}.unidadeconverte u
                inner join conversao_origem on (
                    u.fkmedicamento = conversao_origem.fkmedicamento
                    and u.idsegmento = conversao_origem.idsegmento
                )
        )
        on conflict (fkunidademedida, idsegmento, fkmedicamento)
        do update set fator = excluded.fator
    """
    )

    return db.session.execute(
        query,
        {"idSegmentOrigin": id_segment_origin, "idSegmentDestiny": id_segment_destiny},
    )
