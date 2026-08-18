import json
from datetime import datetime

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
from utils import aws, status


@has_permission(Permission.ADMIN_UNIT_CONVERSION)
def get_conversion_list():
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
            prediction = 1
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

    return result


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

    lambda_client = aws.get_client("lambda", region_name=Config.NIFI_SQS_QUEUE_REGION)
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
