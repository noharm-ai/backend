"""Repository: culture related operations"""

from boto3.dynamodb.conditions import Key

from config import Config
from models.enums import NoHarmENV
from utils import aws


def get_culture_summary_from_dynamodb(schema: str, id_patient: int):
    """Get the culture summary (antibiogram + prediction) by patient from DynamoDB"""

    if Config.ENV == NoHarmENV.TEST.value:
        return []

    dynamodb = aws.get_resource("dynamodb", region_name="sa-east-1")
    table = dynamodb.Table("noharm_cultura_resumo")

    PARTITION_KEY_VALUE = f"{schema}:{id_patient}"

    response = table.query(
        KeyConditionExpression=Key("schema_fkpessoa").eq(PARTITION_KEY_VALUE),
    )

    return response.get("Items", [])
