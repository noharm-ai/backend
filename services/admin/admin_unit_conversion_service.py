import json
from datetime import datetime

from sqlalchemy import text

from config import Config
from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from models.main import (
    DrugAttributes,
    User,
    db,
)
from models.segment import Segment
from services import drug_service as main_drug_service
from services.admin import (
    admin_drug_service,
)
from utils import aws, status


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
