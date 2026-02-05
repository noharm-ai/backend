"""Repository: queries related to prescription visualization"""

import math
import re
from difflib import SequenceMatcher

from models.enums import DrugTypeEnum
from services import drug_service
from services.admin import admin_ai_service
from utils import dateutils, numberutils, prescriptionutils, stringutils


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
        admission_number,
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
        self.admission_number = admission_number
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
        self.drug_results = []

        self._process_drugs()

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
                and i["admissionNumber"] == self.admission_number
            ):
                if "id" in result.keys() and int(result["id"]) > int(i["id"]):
                    continue
                result = i
        return result

    def getExistIntervention(self, idDrug, idPrescription):
        for i in self.interventions:
            if (
                i["idDrug"] == idDrug
                and int(i["idPrescription"]) < idPrescription
                and i["admissionNumber"] == self.admission_number
            ):
                return True

        return False

    def getIntervention(self, idPrescriptionDrug):
        result = {}
        for i in self.interventions:
            if int(i["id"]) == idPrescriptionDrug:
                result = i
        return result

    def get_drugs_by_source(self, source_list: list[str]):
        items = []
        for pd in self.drug_results:
            if pd.get("source") in source_list:
                items.append(pd)

        return items

    def _process_drugs(self):
        """Process drugList and add source information. Save result in drug_results"""

        for pd in self.drugList:
            if pd[0].source is None:
                pd[0].source = "Medicamentos"
            if pd[0].source not in [
                DrugTypeEnum.DRUG.value,
                DrugTypeEnum.SOLUTION.value,
                DrugTypeEnum.PROCEDURE.value,
                DrugTypeEnum.DIET.value,
            ]:
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

                if pd[0].dose:
                    weight = numberutils.none2zero(self.exams["weight"])

                    if weight > 0:
                        weight = weight if weight > 0 else 1

                        doseWeightStr = (
                            stringutils.strFormatBR(
                                round(pd[0].dose / float(weight), 2)
                            )
                            + " "
                            + pdUnit
                            + "/Kg"
                        )

                        if (
                            pd[6].idMeasureUnit != None
                            and pd[6].idMeasureUnit != pdUnit
                            and pd[0].doseconv != None
                        ):
                            calc_doseconv = (
                                pd[0].doseconv
                                if pd[6].useWeight
                                else round(pd[0].doseconv / float(weight), 2)
                            )
                            doseWeightStr += (
                                " ou "
                                + stringutils.strFormatBR(calc_doseconv)
                                + " "
                                + str(pd[6].idMeasureUnit)
                                + "/Kg"
                                + (" (faixa arredondada)" if pd[6].useWeight else "")
                            )

                if (
                    not bool(pd[0].suspendedDate)
                    and pd[6]
                    and pd[6].tube
                    and pd[0].tube
                ):
                    tubeAlert = True

            period, total_period = prescriptionutils.get_prescription_item_period(
                is_cpoe=self.is_cpoe, item_period=pd[0].period, cpoe_period=pd[12]
            )

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

            self.drug_results.append(
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
                    "periodType": pd[0].tp_period,
                    "periodDayInterval": pd[12],
                    "periodMax": pd[0].period_total,  # max period in days
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
                        str(pd[5])
                        if not pdWhiteList and pd[0].source != DrugTypeEnum.DIET.value
                        else "0"
                    ),
                    "source": pd[0].source,
                    "originalSource": pd[0].source,
                    "checked": bool(pd[0].checked or pd[9] == "s"),
                    "suspended": bool(pd[0].suspendedDate),
                    "suspensionDate": dateutils.to_iso(pd[0].suspendedDate),
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
                    "prescriptionDate": dateutils.to_iso(pd.prescription_date),
                    "prescriptionExpire": dateutils.to_iso(pd.prescription_expire),
                    "schedule": self.schedule_to_array(pd[0].schedule),
                    "orderNumber": pd[0].order_number,
                    "intravenous": pd[0].intravenous,
                    "feedingTube": pd[0].tube,
                }
            )

        # Normalize source for records with same idPrescription and grp_solution
        # Group drugs by (idPrescription, grp_solution) with their indices
        groups = {}
        for idx, drug in enumerate(self.drug_results):
            # Skip records where grp_solution is null
            if drug["grp_solution"] is None:
                continue
            key = (drug["idPrescription"], drug["grp_solution"])
            if key not in groups:
                groups[key] = []
            groups[key].append(idx)

        # Check each group for different sources and normalize
        for key, indices in groups.items():
            if len(indices) > 1:
                sources = set()

                for idx in indices:
                    drug_item = self.drug_results[idx]
                    drug_item_source = drug_item["source"]
                    drug_item_whitelist = drug_item["whiteList"]

                    if (
                        drug_item_whitelist
                        and drug_item_source == DrugTypeEnum.SOLUTION.value
                    ):
                        # should not be a Solution to avoid the entire group to became a solution too
                        sources.add(DrugTypeEnum.DRUG.value)
                    else:
                        sources.add(drug_item_source)

                # Only normalize if there are different sources
                if len(sources) > 1:
                    # Priority: "Soluções" > Medicamentos
                    if DrugTypeEnum.SOLUTION.value in sources:
                        normalized_source = DrugTypeEnum.SOLUTION.value
                    else:
                        # Keep first source if no priority matches
                        normalized_source = DrugTypeEnum.DRUG.value

                    # Apply normalized source to all drugs in group in self.drug_results list
                    for idx in indices:
                        self.drug_results[idx]["source"] = normalized_source

    def getInfusionKey(self, pd):
        if self.is_cpoe:
            return pd[0].cpoe_group if pd[0].cpoe_group else pd[0].solutionGroup

        return str(pd[0].idPrescription) + str(pd[0].solutionGroup)

    def get_solution_dose(self, pd):
        """Get solution dose for infusion calculations (always in ml)"""

        solution_unit = "ml"

        prescribed_unit = pd.MeasureUnit.measureunit_nh if pd.MeasureUnit else None
        default_unit = pd.default_measure_unit_nh
        dose = pd[0].dose
        dose_conv = pd[0].doseconv
        has_dose_ranges = pd[6].division if pd[6] else False
        measure_unit_default_convert_factor = pd.measure_unit_convert_factor
        measure_unit_solution_convert_factor = pd.measure_unit_solution_convert_factor

        if has_dose_ranges:
            # cant use doseconv when there are dose ranges

            if measure_unit_default_convert_factor and dose:
                # need to convert dose to ml (without ranges)
                dose_conv = dose * measure_unit_default_convert_factor
            else:
                dose_conv = 0

        if prescribed_unit == solution_unit:
            # dose is already in ml
            return dose

        if default_unit == solution_unit:
            # doseconv is in ml
            return dose_conv

        if measure_unit_solution_convert_factor and dose_conv:
            # need to convert dose to ml
            return dose_conv / measure_unit_solution_convert_factor

        return 0

    def getInfusionList(self):
        """Infusion info for total volume calculation. Keyed by solution group. Used in Solution Calculator"""
        result = {}

        for pd in self.drugList:
            if pd[0].solutionGroup or pd[0].cpoe_group:
                key = self.getInfusionKey(pd)

                if key not in result:
                    result[key] = {
                        "totalVol": 0,
                        "amount": 0,
                        "vol": 0,
                        "speed": 0,
                        "speedUnit": None,
                        "unit": "ml",
                        "disableTotal": False,
                    }

                pd_dose = self.get_solution_dose(pd)

                if pd_dose == 0:
                    # unable to calculate total volume due to dose unit conversion
                    result[key]["disableTotal"] = True

                if not bool(pd[0].suspendedDate):
                    if pd[6] and pd[6].amount and pd[6].amountUnit:
                        result[key]["vol"] = pd_dose
                        result[key]["amount"] = pd[6].amount
                        result[key]["unit"] = pd[6].amountUnit

                        if (
                            pd[2]
                            and pd[2].id.lower() != "ml"
                            and pd[2].id.lower() == pd[6].amountUnit.lower()
                        ):
                            result[key]["vol"] = pd_dose = round(
                                pd[0].dose / pd[6].amount, 5
                            )

                    if pd[6] and pd[6].amount and pd[6].amountUnit is None:
                        result[key]["vol"] = pd_dose = pd[6].amount

                    if pd[0].solutionDose:
                        result[key]["speed"] = pd[0].solutionDose

                    if pd[0].solutionUnit:
                        result[key]["speedUnit"] = pd[0].solutionUnit

                    result[key]["totalVol"] += pd_dose if pd_dose else 0
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
    def infer_substance_ml(pDrugs):
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
    def infer_substance_fuzzy(
        concilia_drugs, prescription_drugs, min_similarity_threshold=0.7
    ):
        """
        Match each drug in concilia_drugs with the best matching drug in prescription_drugs by name.
        Uses fuzzy string matching to find the most similar drug name.

        Args:
            concilia_drugs: List of dictionaries from conciliaList (pDrugs parameter)
            prescription_drugs: List of dictionaries from current prescription (current_prescription_drugs parameter)

        Returns:
            Updated concilia_drugs list with matched sctid from prescription_drugs
        """

        def get_similarity(name1, name2):
            """Calculate similarity ratio between two drug names (case-insensitive)"""
            if not name1 or not name2:
                return 0.0

            # Normalize strings: lowercase and strip whitespace
            name1_norm = stringutils.prepare_drug_name(name1)
            name2_norm = stringutils.prepare_drug_name(name2)

            return SequenceMatcher(None, name1_norm, name2_norm).ratio()

        # For each drug in concilia_drugs, find the best match in prescription_drugs
        for concilia_drug in concilia_drugs:
            if not concilia_drug.get("drug"):
                continue

            if concilia_drug.get("idDrug") != 0:
                concilia_drug["sctid_infer"] = concilia_drug["idSubstance"]
                continue

            best_match = None
            best_similarity = 0.0

            # Find the best matching prescription drug by name
            for prescription_drug in prescription_drugs:
                if not prescription_drug.get("drug"):
                    continue

                similarity = get_similarity(
                    concilia_drug["drug"], prescription_drug["drug"]
                )

                if similarity > best_similarity:
                    best_similarity = similarity
                    best_match = prescription_drug

                similarity = get_similarity(
                    concilia_drug["drug"], prescription_drug["substance"]
                )

                if similarity > best_similarity:
                    best_similarity = similarity
                    best_match = prescription_drug

            # If a good match is found, copy the sctid (substance identifier)
            if best_match and best_similarity >= min_similarity_threshold:
                if best_match.get("sctid"):
                    concilia_drug["sctid_infer"] = best_match["sctid"]
                    concilia_drug["matched_drug"] = best_match["drug"]
                    concilia_drug["match_score"] = round(best_similarity, 2)

        return concilia_drugs

    @staticmethod
    def conciliaList(pDrugs, result=[]):
        for pd in pDrugs:
            existsDrug = next(
                (
                    d
                    for d in result
                    if d["idDrug"] == pd[0].idDrug
                    and d["recommendation"] == pd[0].notes
                    and d["dose"] == pd[0].dose
                    and d["frequencyday"] == pd[0].frequency
                    and d["timeRaw"] == pd[0].interval
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
                idmeasureunit = pd[0].idMeasureUnit if pd[0].idMeasureUnit else ""
                idfrequency = pd[0].idFrequency if pd[0].idFrequency else ""

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
                            else {"value": idmeasureunit, "label": idmeasureunit}
                        ),
                        "frequency": (
                            {"value": pd[3].id, "label": pd[3].description}
                            if pd[3]
                            else {"value": idfrequency, "label": idfrequency}
                        ),
                        "frequencyday": pd[0].frequency,
                        "time": prescriptionutils.timeValue(pd[0].interval),
                        "timeRaw": pd[0].interval,
                        "recommendation": pd[0].notes,
                        "sctid": str(pd.Substance.id) if pd.Substance else None,
                        "substance": pd.Substance.name if pd.Substance else None,
                    }
                )

        return result

    @staticmethod
    def cpoeDrugs(drugs, idPrescription):
        for d in drugs:
            drugs[drugs.index(d)]["cpoe"] = d["idPrescription"]
            drugs[drugs.index(d)]["idPrescription"] = idPrescription

        return drugs

    @staticmethod
    def schedule_to_array(schedule):
        results = []

        if not schedule:
            return []

        for i in schedule:
            results.append([dateutils.to_iso(i[0]), dateutils.to_iso(i[1])])

        return sorted(
            results, key=lambda d: d[0] if d[0] != None else None, reverse=True
        )[:10]
