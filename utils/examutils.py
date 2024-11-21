import math
import copy
from . import numberutils, stringutils, dateutils

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
swrtz1Empty = dict(examEmpty, **{"initials": "Schwartz 1", "name": "Schwartz 1"})


class refEmpty:
    ref = initials = min = max = name = ""


def formatExam(value, typeExam, unit, date, segExam, prevValue=None):
    value = numberutils.none2zero(value)

    if typeExam in segExam:
        ref = segExam[typeExam]
        alert = not (
            value >= numberutils.none2zero(ref.min)
            and value <= numberutils.none2zero(ref.max)
        )
    else:
        ref = refEmpty()
        ref.name = typeExam
        ref.initials = typeExam
        alert = False

    prevValue = numberutils.none2zero(prevValue)
    delta = None
    if prevValue > 0 and value > 0:
        delta = round(round(abs(prevValue - value) / prevValue, 2) * 100, 2)
        delta = delta * (-1) if prevValue > value else delta

    return {
        "value": value,
        "unit": stringutils.strNone(unit),
        "alert": alert,
        "date": date,
        "ref": ref.ref,
        "initials": ref.initials,
        "min": ref.min,
        "max": ref.max,
        "name": ref.name,
        "prev": prevValue,
        "delta": delta,
    }


# Modification of Diet in Renal Disease
# based on https://www.kidney.org/content/mdrd-study-equation
# eGFR = 175 x (SCr)-1.154 x (age)-0.203 x 0.742 [if female] x 1.212 [if Black]
def mdrd_calc(cr, birthdate, gender, skinColor):
    if not numberutils.is_float(cr):
        return copy.deepcopy(mdrdEmpty)
    if birthdate is None:
        return copy.deepcopy(mdrdEmpty)

    age = dateutils.data2age(birthdate.isoformat())
    if age == 0:
        return copy.deepcopy(mdrdEmpty)

    eGFR = 175 * (float(cr)) ** (-1.154) * (age) ** (-0.203) if cr > 0 else 0

    if gender == "F":
        eGFR *= 0.742
    if _skinChar(skinColor) in ["N", "P"]:
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
    if not numberutils.is_float(cr):
        return copy.deepcopy(cgEmpty)
    if not numberutils.is_float(weight):
        return copy.deepcopy(cgEmpty)
    if birthdate is None:
        return copy.deepcopy(cgEmpty)

    age = dateutils.data2age(birthdate.isoformat())
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
    if not numberutils.is_float(cr):
        return copy.deepcopy(ckdEmpty)
    if birthdate is None:
        return copy.deepcopy(ckdEmpty)

    age = dateutils.data2age(birthdate.isoformat())
    if age == 0:
        return copy.deepcopy(ckdEmpty)

    if gender == "F":
        g = 0.7
        s = 166 if _skinChar(skinColor) in ["N", "P"] else 144
        e = -1.209 if float(cr) > g else -0.329
    else:
        g = 0.9
        s = 163 if _skinChar(skinColor) in ["N", "P"] else 141
        e = -1.209 if float(cr) > g else -0.411

    eGFR = s * (float(cr) / g) ** (e) * (0.993) ** (age) if cr > 0 else 0

    unit = "ml/min/1.73"
    adjust = False

    if numberutils.is_float(height) and numberutils.is_float(weight):
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
    if not numberutils.is_float(cr):
        return copy.deepcopy(ckdEmpty)
    if birthdate is None:
        return copy.deepcopy(ckdEmpty)

    age = dateutils.data2age(birthdate.isoformat())
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
    if not numberutils.is_float(cr):
        return copy.deepcopy(swrtz2Empty)
    if not numberutils.is_float(height):
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


def schwartz1_calc(cr, birthdate, gender, height):
    if not numberutils.is_float(cr):
        return copy.deepcopy(swrtz1Empty)
    if not numberutils.is_float(height):
        return copy.deepcopy(swrtz1Empty)
    if birthdate is None:
        return copy.deepcopy(swrtz1Empty)

    age = dateutils.data2age(birthdate.isoformat())

    k = 0
    if age <= 2:
        k = 0.45
    elif age > 2 and age <= 12:
        k = 0.55
    else:
        if gender == "F":
            k = 0.55
        else:
            k = 0.7

    eGFR = (k * height) / cr if cr > 0 else 0

    return {
        "value": round(eGFR, 1),
        "ref": "maior que 90 mL/min por 1.73 m²",
        "unit": "mL/min/1.73m²",
        "alert": (eGFR < 90),
        "name": "Schwartz 1",
        "initials": "Schwartz 1",
        "min": 90,
        "max": 120,
    }


def _skinChar(s):
    return " " if s is None else str(s).upper()[0]
