"""Service: Unit Conversion related operations"""

import json

import boto3

from config import Config
from decorators.has_permission_decorator import Permission, has_permission
from models.appendix import MeasureUnit
from models.enums import DefaultMeasureUnitEnum
from models.main import User, db
from models.requests.drug_request import DrugUnitConversionRequest
from repository import unit_conversion_repository
from services.admin import admin_unit_conversion_service


@has_permission(Permission.WRITE_DRUG_ATTRIBUTES)
def get_unit_conversion_for_drug(id_drug: int):
    """Returns unit conversion possibilities for a single drug"""

    configured_measure_units = (
        unit_conversion_repository.get_drugattributes_default_measure_unit_for_drug(
            id_drug=id_drug
        )
    )

    conversion_list = unit_conversion_repository.get_unit_conversion_for_drug(
        id_drug=id_drug
    )

    substanceMeasureUnit = (
        conversion_list[0].default_measureunit if len(conversion_list) > 0 else None
    )

    show_factors = True

    if len(configured_measure_units) > 1:
        # more than one configured unit
        show_factors = False
    elif len(configured_measure_units) == 1:
        if configured_measure_units[0].measureunit_nh != substanceMeasureUnit:
            # configured unit is different from default unit
            show_factors = False

    if len(conversion_list) > 0 and substanceMeasureUnit is None:
        substanceMeasureUnit = DefaultMeasureUnitEnum.UN.value
        show_factors = False

    result = []
    for i in conversion_list:
        is_default_unit = substanceMeasureUnit == i.measureunit_nh

        if is_default_unit:
            factor = 1
        elif show_factors:
            factor = i.factor
        else:
            factor = None

        result.append(
            {
                "id": f"{i.id}-{i.idMeasureUnit}",
                "idMeasureUnit": i.idMeasureUnit,
                "factor": factor,
                "measureUnit": i.description,
                "drugMeasureUnitNh": i.measureunit_nh,
                "default": is_default_unit,
            }
        )

    if substanceMeasureUnit and not any(i["default"] for i in result):
        result.append(
            {
                "id": f"{id_drug}-{substanceMeasureUnit}",
                "idMeasureUnit": substanceMeasureUnit,
                "factor": 1,
                "measureUnit": substanceMeasureUnit,
                "drugMeasureUnitNh": substanceMeasureUnit,
                "default": True,
            }
        )

    return {
        "name": conversion_list[0].name,
        "idDrug": conversion_list[0].id,
        "substanceMeasureUnit": substanceMeasureUnit,
        "conversionList": result,
    }


@has_permission(Permission.WRITE_DRUG_ATTRIBUTES)
def save_unit_conversion_for_drug(
    id_drug: int, request_data: DrugUnitConversionRequest, user_context: User
):
    """Save conversions for a drug, apply to all segments and generate score"""

    id_measure_unit_default = (
        unit_conversion_repository.get_substance_default_measure_unit_for_drug(
            id_drug=id_drug
        )
        or DefaultMeasureUnitEnum.UN.value
    )

    measure_unit = (
        db.session.query(MeasureUnit)
        .filter(MeasureUnit.id == id_measure_unit_default)
        .first()
    )
    if not measure_unit:
        new_unit = MeasureUnit()
        new_unit.id = id_measure_unit_default
        new_unit.idHospital = 1  # default value
        new_unit.description = id_measure_unit_default
        new_unit.measureunit_nh = id_measure_unit_default
        db.session.add(new_unit)
        db.session.flush()

    conversions = []
    for c in request_data.conversion_list:
        # transform to keep compatibility with save_conversions
        conversions.append({"idMeasureUnit": c.id_measure_unit, "factor": c.factor})

    return admin_unit_conversion_service.save_conversions(
        id_drug=id_drug,
        id_segment=1,  # segment not useful in this case
        id_measure_unit_default=id_measure_unit_default,
        conversion_list=conversions,
        user_context=user_context,
        skip_lambda=True,
    )


@has_permission(Permission.WRITE_DRUG_ATTRIBUTES)
def process_drug_scores(id_drug: int, user_context: User):
    lambda_client = boto3.client("lambda", region_name=Config.NIFI_SQS_QUEUE_REGION)
    lambda_response = lambda_client.invoke(
        FunctionName=Config.BACKEND_FUNCTION_NAME,
        InvocationType="Event",
        Payload=json.dumps(
            {
                "command": "lambda_scores.process_drug_scores",
                "schema": user_context.schema,
                "id_user": user_context.id,
                "id_drug": id_drug,
            }
        ),
    )

    # Return Lambda request ID for tracking
    return {
        "request_id": lambda_response.get("ResponseMetadata", {}).get("RequestId"),
        "status_code": lambda_response.get("StatusCode"),
    }
