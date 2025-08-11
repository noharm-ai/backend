"""Service admin frequency related operatons"""

import json

import boto3
from sqlalchemy import asc

from models.main import db, User
from models.appendix import Frequency
from decorators.has_permission_decorator import has_permission, Permission
from exception.validation_error import ValidationError
from utils import status
from config import Config


@has_permission(Permission.ADMIN_FREQUENCIES)
def get_frequencies(has_daily_frequency=None):
    """List all frequencies"""
    q = db.session.query(Frequency)

    if has_daily_frequency is not None:
        if has_daily_frequency:
            q = q.filter(Frequency.dailyFrequency != None)
        else:
            q = q.filter(Frequency.dailyFrequency == None)

    return q.order_by(asc(Frequency.description)).all()


@has_permission(Permission.ADMIN_FREQUENCIES)
def update_frequency(id, daily_frequency, fasting):
    """Update frequency record"""
    freq = Frequency.query.get(id)
    if freq is None:
        raise ValidationError(
            "Registro inexistente", "errors.invalidRecord", status.HTTP_400_BAD_REQUEST
        )

    freq.dailyFrequency = float(daily_frequency)
    freq.fasting = fasting

    db.session.add(freq)
    db.session.flush()

    return freq


@has_permission(Permission.ADMIN_FREQUENCIES)
def infer_frequency(user_context: User):
    """Try to define frequenciadia based on history"""
    lambda_client = boto3.client("lambda", region_name=Config.NIFI_SQS_QUEUE_REGION)
    response = lambda_client.invoke(
        FunctionName=Config.SCORES_FUNCTION_NAME,
        InvocationType="RequestResponse",
        Payload=json.dumps(
            {
                "command": "lambda_frequencies.update_schema_frequencies",
                "schema": user_context.schema,
            }
        ),
    )

    return json.loads(response["Payload"].read().decode("utf-8"))


def list_to_dto(frequencies):
    """convert Frequency list to list[dict]"""
    results = []

    for p in frequencies:
        results.append(
            {
                "id": p.id,
                "name": p.description,
                "dailyFrequency": p.dailyFrequency,
                "fasting": bool(p.fasting),
            }
        )

    return results
