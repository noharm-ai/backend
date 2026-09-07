"""Prescription utils functions."""

from datetime import datetime, timedelta
from typing import Union

from utils import dateutils, numberutils, stringutils


def lenghStay(
    admissionDate: Union[datetime, None], dischargeDate: Union[datetime, None]
):
    if admissionDate is None:
        return ""

    if dischargeDate is None:
        days = int((datetime.today() - admissionDate).days)
    else:
        days = int((dischargeDate - admissionDate).days)

    return 0 if days < 0 else days


def timeValue(time):
    numeric = str(time).strip().replace(" ", "")
    if not numberutils.is_float(numeric):
        return stringutils.strNone(time).strip()
    else:
        timeList = str(time).strip().split(" ")
        if len(timeList) == 1:
            return "Às " + str(time).strip() + " Horas"
        elif len(timeList) < 6:
            return "às " + ("h, às ").join(timeList) + "h"
        else:
            return time


def freqValue(freq):
    if freq == 33:
        return "SN"
    elif freq == 44:
        return "ACM"
    elif freq == 55:
        return "CONT"
    elif freq == 66:
        return "AGORA"
    elif freq == 99:
        return "N/D"
    else:
        return freq


def sortRelations(r):
    return stringutils.remove_accents(r["nameB"])


def interactionsList(drugList, splitStr):
    result = []
    for d in drugList:
        part = d.split(splitStr)
        result.append({"name": part[0], "idDrug": part[1]})

    return result


def get_numeric_drug_attributes_list():
    return [
        "antimicro",
        "mav",
        "controlled",
        "notdefault",
        "elderly",
        "tube",
        "useWeight",
        "whiteList",
        "chemo",
        "dialyzable",
        "fasting",
        "fallRisk",
    ]


# window of inner prescription dates kept in the agg features, in days relative
# to the agg date. mirrors the drug query horizon in
# prescription_view_repository._get_period_filter (cpoe lists prescriptions that
# start up to 2 days ahead) and keeps primary care aggs, which have no period
# filter at all, from growing with the whole admission
PRESCRIPTION_DATES_DAYS_BEHIND = 2
PRESCRIPTION_DATES_DAYS_AHEAD = 2

# hard cap for extreme cases. the most recent dates are kept, since both the next
# and the last prescription date are derived from the end of the list
PRESCRIPTION_DATES_LIMIT = 50


def _get_prescription_dates_window(agg_date):
    """Day bounds ("YYYY-MM-DD") for the inner prescription dates of an agg.

    Returns None when there is no agg date, meaning every date is kept.
    """
    if agg_date is None:
        return None

    # datetime subclasses date: out patient aggs store a plain date
    base = agg_date.date() if isinstance(agg_date, datetime) else agg_date

    return (
        (base - timedelta(days=PRESCRIPTION_DATES_DAYS_BEHIND)).isoformat(),
        (base + timedelta(days=PRESCRIPTION_DATES_DAYS_AHEAD)).isoformat(),
    )


def _is_in_prescription_dates_window(prescription_date: str, window):
    """Whether an ISO prescription date falls inside the agg date window"""
    if window is None:
        return True

    # dates are naive local ISO strings, so the day part compares as plain text
    day = prescription_date.split("T")[0]

    return window[0] <= day <= window[1]


def get_internal_prescription_ids(result: dict):
    id_prescription_list = set()

    drug_list = result["prescription"] + result["solution"] + result["procedures"]

    for d in drug_list:
        # if cpoe search id inside cpoe attr (need refactor)
        id_prescription_list.add(int(d.get("cpoe", d.get("idPrescription"))))

    return list(id_prescription_list)


def getFeatures(result, agg_date: datetime = None, intervals_for_agg_date=False):
    drugList = result["prescription"] + result["solution"] + result["procedures"]

    allergy = alerts = alerts_prescription = pScore = score1 = score2 = score3 = 0
    am = av = control = np = tube = diff = 0
    drugIDs = []
    substanceIDs = []
    substanceClassIDs = []
    frequencies = []
    intervals = []
    drug_attributes = {}
    alert_levels = []
    alert_level = "low"
    department_list = set()
    prescription_dates = set()
    prescription_dates_window = _get_prescription_dates_window(agg_date)

    for attr in get_numeric_drug_attributes_list():
        drug_attributes[attr] = 0

    for d in drugList:
        drugIDs.append(d["idDrug"])

        # individual prescription dates inside the agg prescription: used to
        # prioritize agg prescriptions by their inner prescription dates. dates
        # outside the window are dropped: an old prescription stays in the drug
        # list while it does not expire and would grow the list without ever
        # being the next or the last date
        prescription_date = d.get("prescriptionDate", None)
        if prescription_date and _is_in_prescription_dates_window(
            prescription_date, prescription_dates_window
        ):
            prescription_dates.add(prescription_date)
        if d["idSubstance"] != None:
            substanceIDs.append(d["idSubstance"])
        if d["idSubstanceClass"] != None:
            substanceClassIDs.append(d["idSubstanceClass"])

        if "drugAttributes" in d and d["drugAttributes"] != None:
            for attr in d["drugAttributes"]:
                if attr in drug_attributes:
                    drug_attributes[attr] += int(
                        numberutils.none2zero(d["drugAttributes"][attr])
                    )

        if d["whiteList"] or d["suspended"]:
            continue

        allergy += int(d["allergy"])
        alerts_prescription += len(d["alertsComplete"])
        pScore += int(d["score"])
        score1 += int(d["score"] == "1")
        score2 += int(d["score"] == "2")
        score3 += int(int(d["score"]) > 2)
        am += int(d["am"]) if d["am"] is not None else 0
        av += int(d["av"]) if d["av"] is not None else 0
        np += int(d["np"]) if d["np"] is not None else 0
        control += int(d["c"]) if d["c"] is not None else 0
        diff += int(not d["checked"])
        tube += int(d["tubeAlert"])

        if intervals_for_agg_date:
            # add interval for agg_date
            if (
                agg_date != None
                and d["prescriptionDate"] != None
                and dateutils.to_iso(agg_date).split("T")[0]
                == d["prescriptionDate"].split("T")[0]
            ):
                # must be the same prescription date (individual and agg)
                if d.get("interval", None) != None:
                    times = split_interval(d.get("interval"))
                    for t in times:
                        if t not in intervals:
                            intervals.append(t)
        else:
            # add all intervals
            if d.get("interval", None) != None:
                times = split_interval(d.get("interval"))
                for t in times:
                    if t not in intervals:
                        intervals.append(t)

        intervals.sort()

        if d["frequency"]["value"] != "":
            frequencies.append(d["frequency"]["value"])

        for a in d["alertsComplete"]:
            alert_levels.append(a["level"])

        department_list.add(d["idDepartment"])

    interventions = 0
    for i in result["interventions"]:
        interventions += int(i["status"] == "s")

    exams = result["alertExams"]
    complicationCount = result["complication"]

    if "alertStats" in result:
        # entire prescription (agg features)
        alerts = result["alertStats"]["total"]
        alert_level = result["alertStats"].get("level", "low")
    else:
        # headers
        alerts = alerts_prescription

        if "medium" in alert_levels:
            alert_level = "medium"

        if "high" in alert_levels:
            alert_level = "high"

    protocol_alerts = result.get("protocolAlerts", {}).get("summary", [])
    alerts += len(protocol_alerts)

    global_score = pScore + av + am + exams + alerts + diff

    sorted_prescription_dates = sorted(prescription_dates)
    prescription_dates_truncated = (
        len(sorted_prescription_dates) > PRESCRIPTION_DATES_LIMIT
    )
    if prescription_dates_truncated:
        sorted_prescription_dates = sorted_prescription_dates[
            -PRESCRIPTION_DATES_LIMIT:
        ]

    return {
        "alergy": allergy,
        "allergy": allergy,
        "alerts": alerts,
        "alertLevel": alert_level,
        "prescriptionScore": pScore,
        "scoreOne": score1,
        "scoreTwo": score2,
        "scoreThree": score3,
        "am": am,
        "av": av,
        "controlled": control,
        "np": np,
        "tube": tube,
        "diff": diff,
        "alertExams": exams,
        "interventions": interventions,
        "complication": complicationCount,
        "drugIDs": list(set(drugIDs)),
        "substanceIDs": list(set(substanceIDs)),
        "substanceClassIDs": list(set(substanceClassIDs)),
        "alertStats": (result["alertStats"] if "alertStats" in result else None),
        "clinicalNotesStats": result.get("clinicalNotesStats", None),
        "clinicalNotes": result.get("clinicalNotes", None),
        "frequencies": list(set(frequencies)),
        "processedDate": datetime.today().isoformat(),
        "totalItens": len(drugList),
        "drugAttributes": drug_attributes,
        "intervals": intervals,
        "departmentList": list(department_list),
        "globalScore": global_score,
        "protocolAlerts": protocol_alerts,
        "prescriptionDates": sorted_prescription_dates,
        "prescriptionDatesTruncated": prescription_dates_truncated,
    }


def split_interval(interval):
    if interval != None:
        results = []
        int_array = interval.split(" ")

        for t in int_array:
            if len(t.split(":")) > 1:
                results.append(t.split(":")[0])
            else:
                if t != "":
                    results.append(t)

        return results

    return []


def gen_agg_id(admission_number, id_segment, pdate):
    if admission_number == None or id_segment == None or pdate == None:
        return None

    id = (pdate.year - 2000) * 100000000000000
    id += pdate.month * 1000000000000
    id += pdate.day * 10000000000
    id += id_segment * 1000000000
    id += admission_number

    return id


def get_prescription_item_period(
    is_cpoe: bool, item_period: int | None, cpoe_period: int | None
) -> tuple[str, int]:
    """Get the period of a prescription item."""

    total_period = 0

    if is_cpoe:
        period = "D" + str(round(cpoe_period)) if cpoe_period else ""
        previous_period = item_period if item_period else 0

        if previous_period > 0:
            total_period = numberutils.none2zero(cpoe_period) + numberutils.none2zero(
                item_period
            )
        else:
            total_period = numberutils.none2zero(cpoe_period) + 1
    else:
        period = ("D" + str(item_period) if item_period else "",)
        total_period = numberutils.none2zero(item_period)

    return period, total_period
