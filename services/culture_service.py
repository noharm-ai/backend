"""Service: culture related operations"""

from decimal import Decimal

from repository import culture_repository
from utils import dateutils, logger

# a prediction below this confidence is not shown to the user. Mirrors the
# threshold used by the culture report (services/reports/reports_culture_service).
PREDICTION_MIN_PROBABILITY = 0.6


def get_culture_summary(schema: str, id_patient: int):
    """Get the culture summary of the patient, grouped by drug.

    Called while assembling the prescription view, so a DynamoDB outage must
    degrade the culture card instead of breaking the whole screening page.
    """

    try:
        items = culture_repository.get_culture_summary_from_dynamodb(
            schema=schema, id_patient=id_patient
        )
    except Exception as e:
        logger.backend_logger.error(f"Culture summary from DynamoDB failed: {e}")
        return []

    return _group_by_drug(items)


def _to_float(value):
    """DynamoDB numbers are deserialized as Decimal, which flask cannot serialize"""

    if isinstance(value, Decimal):
        return float(value)

    return value


def _clean_result(result):
    """A blank lab result means pending, same as a missing one"""

    if isinstance(result, str) and result.strip() == "":
        return None

    return result


def _prediction(item: dict, result):
    """Predictions are only relevant while the lab result is still pending"""

    if result is not None:
        return None, None

    prediction = item.get("predict")
    probability = _to_float(item.get("predict_proba"))

    if prediction is None or probability is None:
        return None, None

    if probability <= PREDICTION_MIN_PROBABILITY:
        return None, None

    return prediction, probability


def _group_by_drug(items: list):
    drugs = {}

    for item in items:
        if not item.get("ativo", False):
            continue

        drug = item.get("nomemedicamento")
        if not drug:
            continue

        result = _clean_result(item.get("resultado"))
        prediction, probability = _prediction(item=item, result=result)

        if result is None and prediction is None:
            # neither a lab result nor a confident prediction: nothing to show
            continue

        if drug not in drugs:
            drugs[drug] = {"drug": drug, "items": []}

        drugs[drug]["items"].append(
            {
                "key": item.get("chave"),
                "microorganism": item.get("microorganismo"),
                "material": item.get("nomematerial"),
                "result": result,
                "prediction": prediction,
                "probability": probability,
                "collectionDate": dateutils.to_iso(item.get("datacoleta")),
                "releaseDate": dateutils.to_iso(item.get("dataliberacao")),
            }
        )

    results = []
    for drug in drugs:
        drugs[drug]["items"] = sorted(
            drugs[drug]["items"],
            key=lambda i: i["collectionDate"] if i["collectionDate"] else "",
            reverse=True,
        )
        results.append(drugs[drug])

    return sorted(results, key=lambda d: d["drug"])
