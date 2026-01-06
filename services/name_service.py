"""Service: name related operations"""

import boto3

from decorators.has_permission_decorator import Permission, has_permission


@has_permission(Permission.READ_BASIC_FEATURES)
def get_name_from_dynamo(id_patient: int, config: dict):
    dynamodb = boto3.resource("dynamodb", region_name="sa-east-1")
    table_name = config["getname"]["token"]["url"].split(":")[1]
    table = dynamodb.Table(table_name)

    response = table.get_item(
        Key={
            "schema_fkpessoa": str(id_patient),
        }
    )

    item = response.get("Item")

    if item:
        return {
            "status": "success",
            "idPatient": id_patient,
            "name": item["nome"],
            "data": None,
        }

    return {
        "status": "error",
        "idPatient": id_patient,
        "name": f"Paciente {str(int(id_patient))}",
    }
