import re
import math

from utils.dateutils import to_iso
from services import drug_service
from services.admin import admin_ai_service
from models.enums import DrugTypeEnum
from utils import stringutils, numberutils, prescriptionutils


def _get_legacy_alert(kind):
    config = {
        "it": "int",
        "dt": "dup",
        "dm": "dup",
        "iy": "inc",
        "sl": "isl",
        "rx": "rea",
    }

    return config[kind]


class DrugList:
    def __init__(
        self,
        drugList,
        interventions,
        relations,
        exams,
        agg,
        dialysis,
        alerts,
        is_cpoe=False,
    ):
        self.drugList = drugList
        self.interventions = interventions
        self.relations = relations
        self.alerts = alerts
        self.exams = exams
        self.agg = agg
        self.dialysis = dialysis
        self.is_cpoe = is_cpoe
        self.maxDoseAgg = {}
        self.alertStats = {
            "dup": 0,
            "int": 0,
            "inc": 0,
            "rea": 0,
            "isl": 0,
            "maxTime": 0,
            "maxDose": 0,
            "kidney": 0,
            "liver": 0,
            "elderly": 0,
            "platelets": 0,
            "tube": 0,
            "exams": 0,  # kidney + liver + platelets
            "allergy": 0,  # allergy + rea,
            "interactions": {},
            "total": 0,
            "level": "low",
        }

    def sumAlerts(self):
        # relations stats
        if self.relations["stats"]:
            for k, v in self.relations["stats"].items():
                self.alertStats[_get_legacy_alert(k)] = v
                self.alertStats["interactions"][k] = v
                self.alertStats["total"] += v

        # alerts stats
        if self.alerts["stats"]:
            for k, v in self.alerts["stats"].items():
                self.alertStats[k] = v
                self.alertStats["total"] += v

        # keep legacy data
        if (
            "dm" in self.alertStats["interactions"]
            and "dt" in self.alertStats["interactions"]
        ):
            self.alertStats["dup"] = (
                self.alertStats["interactions"]["dm"]
                + self.alertStats["interactions"]["dt"]
            )

        self.alertStats["maxDose"] = self.alerts["stats"].get(
            "maxDose", 0
        ) + self.alerts["stats"].get("maxDosePlus", 0)

        self.alertStats["exams"] = (
            self.alertStats["exams"]
            + self.alertStats["kidney"]
            + self.alertStats["liver"]
            + self.alertStats["platelets"]
        )

        levels = []
        if self.relations["alerts"]:
            for k, v in self.relations["alerts"].items():
                for alert in v:
                    levels.append(alert["level"])

        if self.alerts["alerts"]:
            for k, v in self.alerts["alerts"].items():
                for alert in v:
                    levels.append(alert["level"])

        if "medium" in levels:
            self.alertStats["level"] = "medium"

        if "high" in levels:
            self.alertStats["level"] = "high"

    @staticmethod
    def sortDrugs(d):
        return stringutils.remove_accents(d["drug"]).lower()

    def getPrevIntervention(self, idDrug, idPrescription):
        result = {}
        for i in self.interventions:
            if (
                i["idDrug"] == idDrug
                and i["status"] == "s"
                and int(i["idPrescription"]) < idPrescription
            ):
                if "id" in result.keys() and int(result["id"]) > int(i["id"]):
                    continue
                result = i
        return result

    def getExistIntervention(self, idDrug, idPrescription):
        result = False
        for i in self.interventions:
            if i["idDrug"] == idDrug and int(i["idPrescription"]) < idPrescription:
                result = True
        return result

    def getIntervention(self, idPrescriptionDrug):
        result = {}
        for i in self.interventions:
            if int(i["id"]) == idPrescriptionDrug:
                result = i
        return result

    def getDrugType(self, pDrugs, source):
        for pd in self.drugList:
            if pd[0].source is None:
                pd[0].source = "Medicamentos"
            if pd[0].source not in source:
                continue

            pdUnit = stringutils.strNone(pd[2].id) if pd[2] else ""
            pdWhiteList = bool(pd[6].whiteList) if pd[6] is not None else False
            doseWeightStr = None
            doseBodySurfaceStr = None

            tubeAlert = False
            alerts = []
            alerts_complete = []

            if self.relations["alerts"] and str(pd[0].id) in self.relations["alerts"]:
                for a in self.relations["alerts"][str(pd[0].id)]:
                    alerts.append(a["text"])
                    alerts_complete.append(a)

            if self.alerts["alerts"] and str(pd[0].id) in self.alerts["alerts"]:
                for a in self.alerts["alerts"][str(pd[0].id)]:
                    alerts.append(a["text"])
                    alerts_complete.append(a)

            if self.exams and pd[6]:
                if pd[6].chemo and pd[0].dose:
                    bs_weight = numberutils.none2zero(self.exams["weight"])
                    bs_height = numberutils.none2zero(self.exams["height"])

                    if bs_weight != 0 and bs_height != 0:
                        body_surface = math.sqrt((bs_weight * bs_height) / 3600)
                        doseBodySurfaceStr = f"""{stringutils.strFormatBR(round(pd[0].dose / body_surface, 2))} {pdUnit}/m²"""

                if pd[6].useWeight and pd[0].dose:
                    weight = numberutils.none2zero(self.exams["weight"])
                    weight = weight if weight > 0 else 1

                    doseWeightStr = (
                        stringutils.strFormatBR(round(pd[0].dose / float(weight), 2))
                        + " "
                        + pdUnit
                        + "/Kg"
                    )

                    if (
                        pd[6].idMeasureUnit != None
                        and pd[6].idMeasureUnit != pdUnit
                        and pd[0].doseconv != None
                    ):
                        doseWeightStr += (
                            " ou "
                            + stringutils.strFormatBR(pd[0].doseconv)
                            + " "
                            + str(pd[6].idMeasureUnit)
                            + "/Kg (faixa arredondada)"
                        )

                if (
                    not bool(pd[0].suspendedDate)
                    and pd[6]
                    and pd[6].tube
                    and pd[0].tube
                ):
                    tubeAlert = True

            total_period = 0
            if self.is_cpoe:
                period = str(round(pd[12])) + "D" if pd[12] else ""
                total_period = numberutils.none2zero(pd[12]) + numberutils.none2zero(
                    pd[0].period
                )
            else:
                period = (str(pd[0].period) + "D" if pd[0].period else "",)
                total_period = numberutils.none2zero(pd[0].period)

            prevNotes = None
            prevNotesUser = None
            if pd[8]:
                prevNotesUser = str(pd[8]).replace("##@", "(").replace("@##", ")")
                prevNotes = re.sub(r"##@(.*)@##", "", str(pd[8]))

            dialyzable = False
            if (
                pd[6] != None
                and pd[6].dialyzable
                and self.dialysis != None
                and self.dialysis != "0"
            ):
                # dialyzable drug and dialysis patient
                dialyzable = True

            pDrugs.append(
                {
                    "idPrescription": str(pd[0].idPrescription),
                    "idPrescriptionDrug": str(pd[0].id),
                    "idDrug": pd[0].idDrug,
                    "idDepartment": pd.idDepartment,
                    "drug": (
                        pd[1].name
                        if pd[1] is not None
                        else "Medicamento " + str(pd[0].idDrug)
                    ),
                    "np": pd[6].notdefault if pd[6] is not None else False,
                    "am": pd[6].antimicro if pd[6] is not None else False,
                    "av": pd[6].mav if pd[6] is not None else False,
                    "c": pd[6].controlled if pd[6] is not None else False,
                    "q": pd[6].chemo if pd[6] is not None else False,
                    "dialyzable": dialyzable,
                    "alergy": bool(pd[0].allergy == "S"),
                    "allergy": bool(pd[0].allergy == "S"),
                    "whiteList": pdWhiteList,
                    "doseWeight": doseWeightStr,
                    "doseBodySurface": doseBodySurfaceStr,
                    "dose": pd[0].dose,
                    "measureUnit": (
                        {"value": pd[2].id, "label": pd[2].description}
                        if pd[2]
                        else {
                            "value": stringutils.strNone(pd[0].idMeasureUnit),
                            "label": stringutils.strNone(pd[0].idMeasureUnit),
                        }
                    ),
                    "frequency": (
                        {"value": pd[3].id, "label": pd[3].description}
                        if pd[3]
                        else {
                            "value": stringutils.strNone(pd[0].idFrequency),
                            "label": stringutils.strNone(pd[0].idFrequency),
                        }
                    ),
                    "dayFrequency": pd[0].frequency,
                    "doseconv": pd[0].doseconv,
                    "time": prescriptionutils.timeValue(pd[0].interval),
                    "interval": pd[0].interval,
                    "recommendation": (
                        pd[0].notes
                        if pd[0].notes and len(pd[0].notes.strip()) > 0
                        else None
                    ),
                    "period": period,
                    "periodFixed": pd[0].period,
                    "totalPeriod": total_period,
                    "periodDates": [],
                    "route": pd[0].route,
                    "grp_solution": (
                        pd[0].cpoe_group if self.is_cpoe else pd[0].solutionGroup
                    ),
                    "stage": (
                        "ACM"
                        if pd[0].solutionACM == "S"
                        else stringutils.strNone(pd[0].solutionPhase)
                        + " x "
                        + stringutils.strNone(pd[0].solutionTime)
                        + " ("
                        + stringutils.strNone(pd[0].solutionTotalTime)
                        + ")"
                    ),
                    "infusion": stringutils.strNone(pd[0].solutionDose)
                    + " "
                    + stringutils.strNone(pd[0].solutionUnit),
                    "score": (
                        str(pd[5]) if not pdWhiteList and source != "Dietas" else "0"
                    ),
                    "source": pd[0].source,
                    "checked": bool(pd[0].checked or pd[9] == "s"),
                    "suspended": bool(pd[0].suspendedDate),
                    "suspensionDate": pd[0].suspendedDate,
                    "status": pd[0].status,
                    "near": pd[0].near,
                    "prevIntervention": self.getPrevIntervention(
                        pd[0].idDrug, pd[0].idPrescription
                    ),
                    "existIntervention": self.getExistIntervention(
                        pd[0].idDrug, pd[0].idPrescription
                    ),
                    "alertsComplete": alerts_complete,
                    "tubeAlert": tubeAlert,
                    "notes": pd[7],
                    "prevNotes": prevNotes,
                    "prevNotesUser": prevNotesUser,
                    "drugInfoLink": pd[11].link if pd[11] != None else None,
                    "idSubstance": pd[11].id if pd[11] != None else None,
                    "idSubstanceClass": pd[11].idclass if pd[11] != None else None,
                    "cpoe_group": pd[0].cpoe_group,
                    "infusionKey": self.getInfusionKey(pd),
                    "formValues": pd[0].form,
                    "drugAttributes": drug_service.to_dict(pd[6]),
                    "prescriptionDate": to_iso(pd.prescription_date),
                    "prescriptionExpire": to_iso(pd.prescription_expire),
                }
            )

        return pDrugs

    def getInfusionKey(self, pd):
        if self.is_cpoe:
            return pd[0].cpoe_group if pd[0].cpoe_group else pd[0].solutionGroup

        return str(pd[0].idPrescription) + str(pd[0].solutionGroup)

    def getInfusionList(self):
        result = {}
        for pd in self.drugList:
            if (pd[0].solutionGroup or pd[0].cpoe_group) and pd[0].source == "Soluções":
                key = self.getInfusionKey(pd)

                if not key in result:
                    result[key] = {
                        "totalVol": 0,
                        "amount": 0,
                        "vol": 0,
                        "speed": 0,
                        "unit": "ml",
                    }

                pdDose = pd[0].dose

                if not bool(pd[0].suspendedDate):
                    if pd[6] and pd[6].amount and pd[6].amountUnit:
                        result[key]["vol"] = pdDose
                        result[key]["amount"] = pd[6].amount
                        result[key]["unit"] = pd[6].amountUnit

                        if (
                            pd[2]
                            and pd[2].id.lower() != "ml"
                            and pd[2].id.lower() == pd[6].amountUnit.lower()
                        ):
                            result[key]["vol"] = pdDose = round(
                                pd[0].dose / pd[6].amount, 3
                            )

                    if pd[6] and pd[6].amount and pd[6].amountUnit is None:
                        result[key]["vol"] = pdDose = pd[6].amount

                    result[key]["speed"] = pd[0].solutionDose

                    result[key]["totalVol"] += pdDose if pdDose else 0
                    result[key]["totalVol"] = round(result[key]["totalVol"], 3)

        return result

    # troca nome do medicamento do paciente
    @staticmethod
    def changeDrugName(pDrugs):
        result = []
        for p in pDrugs:
            if p["idDrug"] == 0:
                p["drug"] = p["time"]
            result.append(p)

        return result

    @staticmethod
    def infer_substance(pDrugs):
        names = []
        for p in pDrugs:
            if p["idDrug"] == 0:
                names.append(p["drug"])

        substances = admin_ai_service.get_substance_by_drug_name(drug_names=names)

        result = []
        for p in pDrugs:
            if p["idDrug"] == 0:
                if p["drug"] in substances:
                    p["sctid_infer"] = substances[p["drug"]]

                result.append(p)
            else:
                result.append(p)

        return result

    @staticmethod
    def conciliaList(pDrugs, result=[]):
        for pd in pDrugs:
            existsDrug = next(
                (
                    d
                    for d in result
                    if d["idDrug"] == pd[0].idDrug
                    and d["recommendation"] == pd[0].notes
                ),
                False,
            )
            valid_sources = [
                DrugTypeEnum.DRUG.value,
                DrugTypeEnum.PROCEDURE.value,
                DrugTypeEnum.SOLUTION.value,
            ]
            if (
                not existsDrug
                and not bool(pd[0].suspendedDate)
                and pd[0].source in valid_sources
            ):
                result.append(
                    {
                        "idPrescription": str(pd[0].idPrescription),
                        "idPrescriptionDrug": str(pd[0].id),
                        "idDrug": pd[0].idDrug,
                        "drug": (
                            pd[1].name
                            if pd[1] is not None
                            else "Medicamento " + str(pd[0].idDrug)
                        ),
                        "dose": pd[0].dose,
                        "measureUnit": (
                            {"value": pd[2].id, "label": pd[2].description}
                            if pd[2]
                            else ""
                        ),
                        "frequency": (
                            {"value": pd[3].id, "label": pd[3].description}
                            if pd[3]
                            else ""
                        ),
                        "time": prescriptionutils.timeValue(pd[0].interval),
                        "recommendation": pd[0].notes,
                        "sctid": str(pd.Substance.id) if pd.Substance else None,
                    }
                )

        return result

    @staticmethod
    def cpoeDrugs(drugs, idPrescription):
        for d in drugs:
            drugs[drugs.index(d)]["cpoe"] = d["idPrescription"]
            drugs[drugs.index(d)]["idPrescription"] = idPrescription

        return drugs
