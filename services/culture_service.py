"""Service: culture related operations"""

import re
import unicodedata
from decimal import Decimal

from models.enums import CultureResultTypeEnum
from repository import culture_repository
from utils import dateutils, logger

# a prediction below this confidence is not shown to the user. Mirrors the
# threshold used by the culture report (services/reports/reports_culture_service).
PREDICTION_MIN_PROBABILITY = 0.6

# The antibiogram result is free text and its wording changes from one hospital
# to the next, so it is classified here instead of on the screen that shows it.
# To support a new wording, add it to "exact" of the proper type; "prefixes"
# catches unenumerated variants of the same word, and "plain" lists the wordings
# that say nothing beyond the type itself (see result_detail).
RESULT_TYPES = {
    CultureResultTypeEnum.RESISTANT: {
        "exact": {"r", "resistente"},
        "prefixes": ("resist",),
        "plain": {"r", "resistente"},
    },
    CultureResultTypeEnum.SUSCEPTIBLE: {
        "exact": {
            "s",
            "sensivel",
            "sensivel,aumentando exposicao",
            "sensivel dose-dependente",
            "intermediario",
        },
        # "susce" covers both spellings: suscetível (pt) and susceptible (en)
        "prefixes": ("sensi", "susce"),
        "plain": {"s", "sensivel"},
    },
}


def _normalize(text) -> str:
    """Accent, case and spacing are not meaningful when reading a result"""

    normalized = unicodedata.normalize("NFKD", f"{text}")
    normalized = "".join(c for c in normalized if not unicodedata.combining(c))

    return re.sub(r"\s+", " ", normalized).strip().lower()


def classify_result(result) -> CultureResultTypeEnum:
    """Tell whether a result (or a prediction) means resistant or susceptible"""

    if result is None:
        return CultureResultTypeEnum.UNKNOWN

    text = _normalize(result)

    for result_type, wordings in RESULT_TYPES.items():
        if text in wordings["exact"]:
            return result_type

    for result_type, wordings in RESULT_TYPES.items():
        if text.startswith(wordings["prefixes"]):
            return result_type

    return CultureResultTypeEnum.UNKNOWN


def result_detail(result, result_type: CultureResultTypeEnum):
    """The wording of a result that the type alone does not convey.

    "Sensível" adds nothing to a card that already groups the drug as
    susceptible, but "Sensível Dose-Dependente" and any unrecognized wording do.
    """

    if result is None:
        return None

    wordings = RESULT_TYPES.get(result_type, {})

    if _normalize(result) in wordings.get("plain", set()):
        return None

    return result


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


def _to_int(value):
    """DynamoDB numbers are deserialized as Decimal, which flask cannot serialize"""

    if isinstance(value, Decimal):
        return int(value)

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
        result_type = classify_result(result)
        prediction, probability = _prediction(item=item, result=result)

        if result is None and prediction is None:
            # neither a lab result nor a confident prediction: nothing to show
            continue

        if drug not in drugs:
            drugs[drug] = {"drug": drug, "items": []}

        drugs[drug]["items"].append(
            {
                "key": item.get("chave"),
                # identifies the culture itself: every drug tested against the
                # same specimen shares it
                "idExamItem": _to_int(item.get("fkitemexame")),
                "microorganism": item.get("microorganismo"),
                "material": item.get("nomematerial"),
                "result": result,
                # resistant / susceptible / unknown, already resolved from the
                # free text of "result"
                "resultType": result_type.value if result is not None else None,
                "resultDetail": result_detail(result, result_type),
                "prediction": prediction,
                # predictions share the alphabet of resultType
                "predictionType": (
                    classify_result(prediction).value
                    if prediction is not None
                    else None
                ),
                "probability": probability,
                "collectionDate": dateutils.to_iso(item.get("datacoleta")),
                "releaseDate": dateutils.to_iso(item.get("dataliberacao")),
            }
        )

    results = []
    for drug in drugs:
        by_date = sorted(
            drugs[drug]["items"],
            key=lambda i: i["collectionDate"] if i["collectionDate"] else "",
            reverse=True,
        )
        # the first item represents the drug wherever it is shown, and a
        # released result always describes it better than a prediction: a drug
        # with an antibiogram must not be read as a prediction just because a
        # newer collection of it is still pending. The sort is stable, so the
        # most recent collection still comes first inside each half.
        drugs[drug]["items"] = sorted(by_date, key=lambda i: i["result"] is None)
        results.append(drugs[drug])

    return sorted(results, key=lambda d: d["drug"])
