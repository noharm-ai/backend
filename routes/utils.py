from flask_api import status
from datetime import date, datetime, timedelta
import unicodedata, copy, re
import logging
import math
from flask_mail import Message, Mail
from sqlalchemy.dialects.postgresql import INTERVAL
from sqlalchemy import between, func


def data2age(birthdate):
    if birthdate is None:
        return ""

    days_in_year = 365.2425
    birthdate = birthdate.split("T")[0]
    birthdate = datetime.strptime(birthdate, "%Y-%m-%d")
    age = int((datetime.today() - birthdate).days / days_in_year)
    return age


def data2month(birthdate):
    if birthdate is None:
        return ""

    month_in_year = 12
    birthdate = birthdate.split("T")[0]
    birthdate = datetime.strptime(birthdate, "%Y-%m-%d")
    age = int((datetime.today() - birthdate).months / month_in_year)
    return age


def validate(date_text):
    try:
        return datetime.strptime(date_text, "%Y-%m-%d")
    except ValueError:
        return date.today()


def lenghStay(admissionDate):
    if admissionDate is None:
        return ""

    days = int((datetime.today() - admissionDate).days)
    return days


def is_float(s):
    try:
        float(s)
        return True
    except:
        return False


def timeValue(time):
    numeric = str(time).strip().replace(" ", "")
    if not is_float(numeric):
        return strNone(time).strip()
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


def none2zero(s):
    return float(s) if is_float(s) else 0


def strNone(s):
    return "" if s is None else str(s)


def strFormatBR(s):
    return f"{s:_.2f}".replace(".", ",").replace("_", ".")


def skinChar(s):
    return " " if s is None else str(s).upper()[0]


def remove_accents(text):
    nfkd_form = unicodedata.normalize("NFKD", text)
    only_ascii = nfkd_form.encode("ASCII", "ignore")
    return only_ascii


def slugify(text):
    text = remove_accents(text).lower()
    return re.sub(r"[\W_]+", "-", str(text))


def sortRelations(r):
    return remove_accents(r["nameB"])


def sortSubstance(s):
    return remove_accents(s["name"])


def interactionsList(drugList, splitStr):
    result = []
    for d in drugList:
        part = d.split(splitStr)
        result.append({"name": part[0], "idDrug": part[1]})

    return result


typeRelations = {}
typeRelations["dm"] = "Duplicidade Medicamentosa"
typeRelations["dt"] = "Duplicidade Terapêutica"
typeRelations["it"] = "Interação Medicamentosa"
typeRelations["iy"] = "Incompatibilidade em Y"
typeRelations["rx"] = "Reatividade Cruzada"
typeRelations["sl"] = "ISL Incompatibilidade em Solução"

examEmpty = {"value": None, "alert": False, "ref": None, "name": None}
mdrdEmpty = dict(
    examEmpty, **{"initials": "MDRD", "name": "Modification of Diet in Renal Disease"}
)
cgEmpty = dict(examEmpty, **{"initials": "CG", "name": "Cockcroft-Gault"})
ckdEmpty = dict(
    examEmpty, **{"initials": "CKD", "name": "Chronic Kidney Disease Epidemiology"}
)
swrtz2Empty = dict(examEmpty, **{"initials": "Schwartz 2", "name": "Schwartz 2"})


class refEmpty:
    ref = initials = min = max = name = ""


def formatExam(exam, typeExam, segExam, prevValue=None):
    if exam is not None:
        value = none2zero(exam.value)

        if typeExam in segExam:
            ref = segExam[typeExam]
            alert = not (value >= none2zero(ref.min) and value <= none2zero(ref.max))
        else:
            ref = refEmpty()
            ref.name = typeExam
            ref.initials = typeExam
            alert = False

        prevValue = none2zero(prevValue)
        delta = None
        if prevValue > 0 and value > 0:
            delta = round(round(abs(prevValue - value) / prevValue, 2) * 100, 2)
            delta = delta * (-1) if prevValue > value else delta

        return {
            "value": value,
            "unit": strNone(exam.unit),
            "alert": alert,
            "date": exam.date.isoformat(),
            "ref": ref.ref,
            "initials": ref.initials,
            "min": ref.min,
            "max": ref.max,
            "name": ref.name,
            "prev": prevValue,
            "delta": delta,
        }
    else:
        examEmpty["date"] = None
        return examEmpty


def period(tuples):
    if len(tuples) > 0:
        last30 = datetime.today() - timedelta(days=30)
        last = datetime.strptime(
            tuples[0].split(" ")[0] + "/" + str(last30.year), "%d/%m/%Y"
        )
        more = last < last30

        dates = list(set([t.split(" ")[0] for t in tuples]))

        return ("+" if more else "") + str(len(dates)) + "D"
    else:
        return "0D"


# Modification of Diet in Renal Disease
# based on https://www.kidney.org/content/mdrd-study-equation
# eGFR = 175 x (SCr)-1.154 x (age)-0.203 x 0.742 [if female] x 1.212 [if Black]
def mdrd_calc(cr, birthdate, gender, skinColor):
    if not is_float(cr):
        return copy.deepcopy(mdrdEmpty)
    if birthdate is None:
        return copy.deepcopy(mdrdEmpty)

    age = data2age(birthdate.isoformat())
    if age == 0:
        return copy.deepcopy(mdrdEmpty)

    eGFR = 175 * (float(cr)) ** (-1.154) * (age) ** (-0.203) if cr > 0 else 0

    if gender == "F":
        eGFR *= 0.742
    if skinChar(skinColor) in ["N", "P"]:
        eGFR *= 1.212

    return {
        "value": round(eGFR, 1),
        "ref": "maior que 50 ml/min/1.73",
        "unit": "ml/min/1.73",
        "alert": (eGFR < 50),
        "name": "Modification of Diet in Renal Disease",
        "initials": "MDRD",
        "min": 50,
        "max": 120,
    }


# Cockcroft-Gault
# based on https://www.kidney.org/professionals/KDOQI/gfr_calculatorCoc
# CCr = {((140–age) x weight)/(72xSCr)} x 0.85 (if female)
def cg_calc(cr, birthdate, gender, weight):
    if not is_float(cr):
        return copy.deepcopy(cgEmpty)
    if not is_float(weight):
        return copy.deepcopy(cgEmpty)
    if birthdate is None:
        return copy.deepcopy(cgEmpty)

    age = data2age(birthdate.isoformat())
    if age == 0:
        return copy.deepcopy(cgEmpty)

    ccr = ((140 - age) * float(weight)) / (72 * float(cr)) if cr > 0 else 0
    if gender == "F":
        ccr *= 0.85

    return {
        "value": round(ccr, 1),
        "ref": "maior que 50 mL/min",
        "unit": "mL/min",
        "alert": (ccr < 50),
        "name": "Cockcroft-Gault",
        "initials": "CG",
        "min": 50,
        "max": 120,
    }


# Chronic Kidney Disease Epidemiology Collaboration
# based on https://www.kidney.org/professionals/kdoqi/gfr_calculator
def ckd_calc(cr, birthdate, gender, skinColor, height, weight):
    if not is_float(cr):
        return copy.deepcopy(ckdEmpty)
    if birthdate is None:
        return copy.deepcopy(ckdEmpty)

    age = data2age(birthdate.isoformat())
    if age == 0:
        return copy.deepcopy(ckdEmpty)

    if gender == "F":
        g = 0.7
        s = 166 if skinChar(skinColor) in ["N", "P"] else 144
        e = -1.209 if float(cr) > g else -0.329
    else:
        g = 0.9
        s = 163 if skinChar(skinColor) in ["N", "P"] else 141
        e = -1.209 if float(cr) > g else -0.411

    eGFR = s * (float(cr) / g) ** (e) * (0.993) ** (age) if cr > 0 else 0

    unit = "ml/min/1.73"
    adjust = False

    if is_float(height) and is_float(weight):
        eGFR *= math.sqrt((float(height) * float(weight)) / 3600) / (1.73)
        unit = "ml/min"
        adjust = True

    return {
        "value": round(eGFR, 1),
        "ref": "maior que 50 " + unit,
        "unit": unit,
        "alert": (eGFR < 50),
        "name": "Chronic Kidney Disease Epidemiology"
        + (" (Adjusted)" if adjust else ""),
        "initials": "CKD" + ("-A" if adjust else ""),
        "min": 50,
        "max": 120,
        "adjust": adjust,
    }


# Chronic Kidney Disease Epidemiology Collaboration (2021)
def ckd_calc_21(cr, birthdate, gender):
    if not is_float(cr):
        return copy.deepcopy(ckdEmpty)
    if birthdate is None:
        return copy.deepcopy(ckdEmpty)

    age = data2age(birthdate.isoformat())
    if age == 0:
        return copy.deepcopy(ckdEmpty)

    if gender == "F":
        g = 0.7
        s = 1.012
        e = -1.200 if float(cr) > g else -0.241
    else:
        g = 0.9
        s = 1
        e = -1.200 if float(cr) > g else -0.302

    eGFR = 142 * (float(cr) / g) ** (e) * (0.9938) ** (age) * s if cr > 0 else 0

    unit = "ml/min/1.73"

    return {
        "value": round(eGFR, 1),
        "ref": "maior que 50 " + unit,
        "unit": unit,
        "alert": (eGFR < 50),
        "name": "Chronic Kidney Disease Epidemiology 2021",
        "initials": "CKD 2021",
        "min": 50,
        "max": 120,
        "adjust": False,
    }


# Schwartz (2) Formula
# based on https://link.springer.com/article/10.1007%2Fs00467-014-3002-5
def schwartz2_calc(cr, height):
    if not is_float(cr):
        return copy.deepcopy(swrtz2Empty)
    if not is_float(height):
        return copy.deepcopy(swrtz2Empty)

    eGFR = (0.413 * height) / cr if cr > 0 else 0

    return {
        "value": round(eGFR, 1),
        "ref": "maior que 90 mL/min por 1.73 m²",
        "unit": "mL/min/1.73m²",
        "alert": (eGFR < 90),
        "name": "Schwartz 2",
        "initials": "Schwartz 2",
        "min": 90,
        "max": 120,
    }


def tryCommit(db, recId, allow=True):
    if not allow:
        db.session.rollback()
        db.session.close()
        db.session.remove()
        return {
            "status": "error",
            "message": "Usuário não autorizado",
        }, status.HTTP_401_UNAUTHORIZED

    try:
        db.session.commit()
        db.session.close()
        db.session.remove()

        return {"status": "success", "data": recId}, status.HTTP_200_OK
    except AssertionError as e:
        db.session.rollback()
        db.session.close()
        db.session.remove()

        logging.basicConfig()
        logger = logging.getLogger("noharm.backend")
        logger.error(str(e))

        return {"status": "error", "message": str(e)}, status.HTTP_400_BAD_REQUEST
    except Exception as e:
        db.session.rollback()
        db.session.close()
        db.session.remove()

        logging.basicConfig()
        logger = logging.getLogger("noharm.backend")
        logger.error(str(e))

        return {
            "status": "error",
            "message": "Ocorreu um erro inesperado.",
        }, status.HTTP_500_INTERNAL_SERVER_ERROR


def getFeatures(result):
    drugList = result["data"]["prescription"]
    drugList.extend(result["data"]["solution"])
    drugList.extend(result["data"]["procedures"])

    allergy = alerts = pScore = score1 = score2 = score3 = 0
    am = av = control = np = tube = diff = 0
    drugIDs = []
    substanceIDs = []
    substanceClassIDs = []
    frequencies = []
    for d in drugList:
        drugIDs.append(d["idDrug"])
        if d["idSubstance"] != None:
            substanceIDs.append(d["idSubstance"])
        if d["idSubstanceClass"] != None:
            substanceClassIDs.append(d["idSubstanceClass"])

        if d["whiteList"] or d["suspended"]:
            continue

        allergy += int(d["allergy"])
        alerts += len(d["alerts"])
        pScore += int(d["score"])
        score1 += int(d["score"] == "1")
        score2 += int(d["score"] == "2")
        score3 += int(int(d["score"]) > 2)
        am += int(d["am"]) if not d["am"] is None else 0
        av += int(d["av"]) if not d["av"] is None else 0
        np += int(d["np"]) if not d["np"] is None and not d["existIntervention"] else 0
        control += int(d["c"]) if not d["c"] is None else 0
        diff += int(not d["checked"])
        tube += int(d["tubeAlert"])

        if d["frequency"]["value"] != "":
            frequencies.append(d["frequency"]["value"])

    interventions = 0
    for i in result["data"]["interventions"]:
        interventions += int(i["status"] == "s")

    exams = result["data"]["alertExams"]
    complicationCount = result["data"]["complication"]

    return {
        "alergy": allergy,
        "allergy": allergy,
        "alerts": alerts,
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
        "alertStats": (
            result["data"]["alertStats"] if "alertStats" in result["data"] else None
        ),
        "frequencies": list(set(frequencies)),
        "processedDate": datetime.today().isoformat(),
        "totalItens": len(drugList),
    }


def sendEmail(subject, sender, emails, html):
    try:
        msg = Message()
        mail = Mail()
        msg.subject = subject
        msg.sender = sender
        msg.recipients = emails
        msg.html = html
        mail.send(msg)
    except:
        print("Erro ao enviar email")


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
    id = (pdate.year - 2000) * 100000000000000
    id += pdate.month * 1000000000000
    id += pdate.day * 10000000000
    id += id_segment * 1000000000
    id += admission_number

    return id
