from datetime import datetime
from sqlalchemy.dialects.postgresql import INTERVAL
from sqlalchemy import between, func

from . import numberutils, stringutils, dateutils


def lenghStay(admissionDate):
    if admissionDate is None:
        return ""

    days = int((datetime.today() - admissionDate).days)
    return days


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


def get_internal_prescription_ids(result: dict):
    id_prescription_list = set()

    drug_list = result["prescription"]
    drug_list.extend(result["solution"])
    drug_list.extend(result["procedures"])

    for d in drug_list:
        # if cpoe search id inside cpoe attr (need refactor)
        id_prescription_list.add(int(d.get("cpoe", d.get("idPrescription"))))

    return list(id_prescription_list)


def getFeatures(result, agg_date: datetime = None, intervals_for_agg_date=False):
    drugList = result["prescription"]
    drugList.extend(result["solution"])
    drugList.extend(result["procedures"])

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

    for attr in get_numeric_drug_attributes_list():
        drug_attributes[attr] = 0

    for d in drugList:
        drugIDs.append(d["idDrug"])
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
        am += int(d["am"]) if not d["am"] is None else 0
        av += int(d["av"]) if not d["av"] is None else 0
        np += int(d["np"]) if not d["np"] is None else 0
        control += int(d["c"]) if not d["c"] is None else 0
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
                        if not t in intervals:
                            intervals.append(t)
        else:
            # add all intervals
            if d.get("interval", None) != None:
                times = split_interval(d.get("interval"))
                for t in times:
                    if not t in intervals:
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

    global_score = pScore + av + am + exams + alerts + diff

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


def get_period_filter(query, model, agg_date, is_pmc, is_cpoe):
    if not is_pmc:
        if is_cpoe:
            query = query.filter(
                between(
                    func.date(agg_date),
                    func.date(model.date - func.cast("2 DAY", INTERVAL)),
                    func.coalesce(func.date(model.expire), func.date(agg_date)),
                )
            )
        else:
            query = query.filter(
                between(
                    func.date(agg_date),
                    func.date(model.date),
                    func.coalesce(func.date(model.expire), func.date(agg_date)),
                )
            )

    return query


def gen_agg_id(admission_number, id_segment, pdate):
    if admission_number == None or id_segment == None or pdate == None:
        return None

    id = (pdate.year - 2000) * 100000000000000
    id += pdate.month * 1000000000000
    id += pdate.day * 10000000000
    id += id_segment * 1000000000
    id += admission_number

    return id
