"""Service: culture related operations"""

import re
import unicodedata
from decimal import Decimal

from models.enums import CultureAlternativeModeEnum, CultureResultTypeEnum
from repository import culture_repository, substance_repository
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


def _to_sctid(value):
    """The substance id keys the culture against the prescription, and DynamoDB
    can hand it over as a number or as a string"""

    if value is None or value == "":
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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
            drugs[drug] = {
                "drug": drug,
                # the substance the lab tested and its class, which is what
                # lets a culture be compared to a prescribed item
                # (services/alert_service)
                "sctid": _to_sctid(item.get("sctid")),
                "idSubstanceClass": item.get("idclasse"),
                "items": [],
            }
        elif drugs[drug]["sctid"] is None:
            # only some collections of a drug may carry the mapping
            drugs[drug]["sctid"] = _to_sctid(item.get("sctid"))
            drugs[drug]["idSubstanceClass"] = item.get("idclasse")

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


def is_resistant_in_use(drug: dict) -> bool:
    """A released resistant antibiogram for a drug the prescription carries.

    The same comparison that raises the cultureResistant alert
    (services/alert_service), read from the flagged summary. A predicted
    resistance never qualifies: the collection is still pending and the
    prediction must not be read as the lab result.
    """

    items = drug.get("items") or []
    if not items:
        return False

    # the first item represents the drug (_group_by_drug puts released
    # results first)
    current = items[0]

    return bool(
        drug.get("prescribed")
        and current.get("result") is not None
        and current.get("resultType") == CultureResultTypeEnum.RESISTANT.value
    )


def get_culture_stats(cultures: list) -> dict:
    """What the prescription screen needs from the cultures without loading
    them: the culture card sits behind a tab, and the tab itself has to say
    that a resistant drug is in use. The cultures themselves are served by
    prescription_view_service.route_get_prescription_cultures on demand.
    """

    return {
        "resistantInUse": sum(1 for drug in cultures or [] if is_resistant_in_use(drug))
    }


# the class keys the culture against the prescription (services/alert_service)
# and is resolved into "prescribed" before the card reads it; the exam item id
# only tells rows of the same specimen apart, which the card never does. The
# substance id stays: it is what the card asks the alternatives of a
# prescribed drug by (route_get_prescription_culture_alternatives)
CARD_HIDDEN_DRUG_FIELDS = ("idSubstanceClass",)
CARD_HIDDEN_ITEM_FIELDS = ("idExamItem",)


def to_card(cultures: list) -> list:
    """The summary in the shape the culture card reads (features/culture)."""

    card = []

    for drug in cultures or []:
        entry = {k: v for k, v in drug.items() if k not in CARD_HIDDEN_DRUG_FIELDS}
        entry["items"] = [
            {k: v for k, v in item.items() if k not in CARD_HIDDEN_ITEM_FIELDS}
            for item in drug.get("items") or []
        ]
        card.append(entry)

    return card


def culture_sctids(cultures: list) -> list:
    """Every substance the antibiograms tested, for the level lookup"""

    return [drug["sctid"] for drug in cultures or [] if drug.get("sctid") is not None]


def _specimen_key(item: dict):
    """What tells one culture apart from another: the antibiogram of a specimen
    tests many drugs against the same microorganism, and an alternative only
    counts when it was tested in that very specimen. The exam item id says it;
    without one, the collection itself has to."""

    if item.get("idExamItem") is not None:
        return ("exam", item["idExamItem"])

    return (
        "collection",
        item.get("microorganism"),
        item.get("material"),
        item.get("collectionDate"),
    )


def _released_type(item: dict):
    """The result type of a released antibiogram, never of a prediction"""

    if item.get("result") is None:
        return None

    return item.get("resultType")


def _level_of(substances: dict, sctid) -> int | None:
    entry = substances.get(_sctid_key(sctid)) if sctid is not None else None

    return entry.get("atbLevel") if entry else None


def _sctid_key(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _alternative_sort_key(alternative: dict):
    # the least aggressive option first, the unclassified ones last: they
    # cannot be placed on the scale, and the card says so instead of guessing
    level = alternative.get("atbLevel")

    return (level is None, level if level is not None else 0, alternative["drug"])


def _susceptible_in_specimen(
    cultures: list, specimen, sctid: int, substances: dict
) -> list:
    """Every other drug that tested susceptible in the same specimen"""

    found = {}

    for drug in cultures or []:
        if _sctid_key(drug.get("sctid")) == sctid:
            continue

        for item in drug.get("items") or []:
            print("drugitem", drug["drug"])
            if _specimen_key(item) != specimen:
                print("removed 1", _specimen_key(item), specimen)
                continue

            if _released_type(item) != CultureResultTypeEnum.SUSCEPTIBLE.value:
                print("removed 2", _released_type(item))
                continue

            # a drug tested twice in the same specimen is still one option
            found.setdefault(
                drug["drug"],
                {
                    "drug": drug["drug"],
                    "sctid": _sctid_key(drug.get("sctid")),
                    "atbLevel": _level_of(substances, drug.get("sctid")),
                    "result": item.get("result"),
                    "resultDetail": item.get("resultDetail"),
                },
            )

    return sorted(found.values(), key=_alternative_sort_key)


def build_alternatives(cultures: list, sctid, substances: dict) -> dict:
    """What the antibiograms suggest in place of a prescribed antimicrobial.

    For every released result of the substance: resistant, the susceptible
    drugs of the same specimen, in AWaRe order (escalation); susceptible, the
    susceptible drugs of the same specimen that are less aggressive on the
    AWaRe scale (de-escalation). A prediction never suggests anything: the
    collection is still pending, and the prediction is not the lab result.

    :param cultures: the culture summary (get_culture_summary)
    :param sctid: the prescribed substance
    :param substances: {sctid: {"name", "atbLevel"}} of the substances involved
        (repository/substance_repository.get_antimicrobial_levels)
    """

    sctid = _sctid_key(sctid)
    level = _level_of(substances, sctid)
    substance = substances.get(sctid) or {}

    result = {
        "sctid": sctid,
        "substance": {"name": substance.get("name"), "atbLevel": level},
        "drug": None,
        "cultures": [],
    }

    if sctid is None:
        return result

    seen_specimens = set()

    for drug in cultures or []:
        if _sctid_key(drug.get("sctid")) != sctid:
            continue

        # the lab may call the substance by more than one name: the first is
        # the one the card shows
        if result["drug"] is None:
            result["drug"] = drug.get("drug")

        for item in drug.get("items") or []:
            result_type = _released_type(item)

            if result_type == CultureResultTypeEnum.RESISTANT.value:
                mode = CultureAlternativeModeEnum.ESCALATION
            elif result_type == CultureResultTypeEnum.SUSCEPTIBLE.value:
                mode = CultureAlternativeModeEnum.DEESCALATION
            else:
                # pending, or a wording the classifier could not read: nothing
                # to compare the other drugs to
                continue

            print("item", item)
            print("result_type", result_type)
            print("mode", mode.value)

            specimen = _specimen_key(item)
            if specimen in seen_specimens:
                continue
            seen_specimens.add(specimen)

            alternatives = _susceptible_in_specimen(
                cultures=cultures, specimen=specimen, sctid=sctid, substances=substances
            )

            print("alternatives", alternatives)

            if mode == CultureAlternativeModeEnum.DEESCALATION:
                # without a level on either side nothing is "less aggressive"
                alternatives = [
                    a
                    for a in alternatives
                    if level is not None
                    and a["atbLevel"] is not None
                    and a["atbLevel"] < level
                ]

            result["cultures"].append(
                {
                    "idExamItem": item.get("idExamItem"),
                    "microorganism": item.get("microorganism"),
                    "material": item.get("material"),
                    "collectionDate": item.get("collectionDate"),
                    "releaseDate": item.get("releaseDate"),
                    "result": item.get("result"),
                    "resultType": result_type,
                    "mode": mode.value,
                    "alternatives": alternatives,
                }
            )

    # the most recent specimen first, whatever drug entry it came from
    result["cultures"].sort(key=lambda c: c["collectionDate"] or "", reverse=True)

    return result


def has_alternatives(cultures: list, sctid, substances: dict) -> bool:
    """Whether build_alternatives has anything to suggest for the substance"""

    return any(
        len(culture["alternatives"]) > 0
        for culture in build_alternatives(
            cultures=cultures, sctid=sctid, substances=substances
        )["cultures"]
    )


def flag_alternatives(cultures: list, substances: dict) -> list:
    """Tell the card which prescribed drugs have an alternative to offer.

    The alternatives themselves are fetched on demand
    (route_get_prescription_culture_alternatives): the card only needs to
    know whether to offer the button, and a susceptible drug with nothing
    less aggressive to step down to must not offer it.
    """

    for drug in cultures or []:
        if not drug.get("prescribed"):
            continue

        print("PRESCRIBED: ", drug.get("drug"))

        drug["hasAlternatives"] = has_alternatives(
            cultures=cultures, sctid=drug.get("sctid"), substances=substances
        )

        print("hasalternatives", drug["hasAlternatives"])

    return cultures


def get_antimicrobial_levels(cultures: list, sctid=None) -> dict:
    """The AWaRe levels of every substance the antibiograms tested, plus the
    prescribed one, which the lab may not have tested by that name"""

    sctids = culture_sctids(cultures)

    if sctid is not None:
        sctids.append(sctid)

    return substance_repository.get_antimicrobial_levels(sctids=sctids)


def get_alternatives(cultures: list, sctid) -> dict:
    """build_alternatives with the levels read from the database"""

    return build_alternatives(
        cultures=cultures,
        sctid=sctid,
        substances=get_antimicrobial_levels(cultures=cultures, sctid=sctid),
    )
