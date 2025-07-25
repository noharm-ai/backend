"""Service: module for drug alerts"""

import re
from typing import List

from models.enums import DrugTypeEnum, DrugAlertTypeEnum, DrugAlertLevelEnum
from models.main import Drug, DrugAttributes
from models.prescription import PrescriptionDrug
from models.appendix import Frequency
from utils import numberutils, stringutils


def find_alerts(
    drug_list,
    exams: dict,
    dialisys: str,
    pregnant: bool,
    lactating: bool,
    schedules_fasting: List[str],
    cn_data: dict,
):
    """
    Find alerts for a list of drugs
    :param drug_list: list of drugs"""
    filtered_list = _filter_drug_list(drug_list=drug_list)
    dose_total = _get_dose_total(drug_list=filtered_list, exams=exams)
    alerts = {}
    stats = _get_empty_stats()

    def add_alert(a, handling_types=[]):
        if a != None:
            key = a["idPrescriptionDrug"]
            stats[a["type"]] += 1
            a["text"] = re.sub(" {2,}", "", a["text"])
            a["text"] = re.sub("\n", "", a["text"])

            a["handling"] = a["type"] in handling_types

            if key not in alerts:
                alerts[key] = [a]
            else:
                alerts[key].append(a)

    for item in filtered_list:
        prescription_drug: PrescriptionDrug = item[0]
        drug: Drug = item[1]
        measure_unit_convert_factor = (
            item.measure_unit_convert_factor
            if item.measure_unit_convert_factor != None
            else 1
        )
        drug_attributes: DrugAttributes = item[6]
        prescription_expire_date = item[10]
        frequency = item[3]
        handling_types = item.substance_handling_types

        # kidney alert
        add_alert(
            _alert_kidney(
                prescription_drug=prescription_drug,
                drug_attributes=drug_attributes,
                exams=exams,
                dialysis=dialisys,
            ),
            handling_types=handling_types,
        )

        # liver alert
        add_alert(
            _alert_liver(
                prescription_drug=prescription_drug,
                drug_attributes=drug_attributes,
                exams=exams,
            ),
            handling_types=handling_types,
        )

        # platelets
        add_alert(
            _alert_platelets(
                prescription_drug=prescription_drug,
                drug_attributes=drug_attributes,
                exams=exams,
            ),
            handling_types=handling_types,
        )

        # elderly
        add_alert(
            _alert_elderly(
                prescription_drug=prescription_drug,
                drug_attributes=drug_attributes,
                exams=exams,
            ),
            handling_types=handling_types,
        )

        # tube
        add_alert(
            _alert_tube(
                prescription_drug=prescription_drug, drug_attributes=drug_attributes
            ),
            handling_types=handling_types,
        )

        # allergy
        add_alert(
            _alert_allergy(prescription_drug=prescription_drug),
            handling_types=handling_types,
        )

        # maximum treatment period
        add_alert(
            _alert_max_time(
                prescription_drug=prescription_drug, drug_attributes=drug_attributes
            ),
            handling_types=handling_types,
        )

        # max dose
        add_alert(
            _alert_max_dose(
                prescription_drug=prescription_drug,
                drug_attributes=drug_attributes,
                exams=exams,
                measure_unit_convert_factor=measure_unit_convert_factor,
            ),
            handling_types=handling_types,
        )

        # max dose total
        add_alert(
            _alert_max_dose_total(
                prescription_drug=prescription_drug,
                drug_attributes=drug_attributes,
                exams=exams,
                prescription_expire_date=prescription_expire_date,
                dose_total=dose_total,
            ),
            handling_types=handling_types,
        )

        # IRA
        add_alert(
            _alert_ira(
                prescription_drug=prescription_drug,
                drug=drug,
                exams=exams,
                prescription_expire_date=prescription_expire_date,
                dose_total=dose_total,
                dialysis=dialisys,
                cn_data=cn_data,
            ),
            handling_types=handling_types,
        )

        # pregnant
        add_alert(
            _alert_pregnant(
                prescription_drug=prescription_drug,
                drug_attributes=drug_attributes,
                pregnant=pregnant,
            ),
            handling_types=handling_types,
        )

        # lactating
        add_alert(
            _alert_lactating(
                prescription_drug=prescription_drug,
                drug_attributes=drug_attributes,
                lactating=lactating,
            ),
            handling_types=handling_types,
        )

        # fasting
        add_alert(
            _alert_fasting(
                prescription_drug=prescription_drug,
                drug_attributes=drug_attributes,
                frequency=frequency,
                schedules_fasting=schedules_fasting,
            ),
            handling_types=handling_types,
        )

    return {"alerts": alerts, "stats": stats}


def _get_empty_stats():
    stats = {}
    for t in DrugAlertTypeEnum:
        stats[t.value] = 0

    return stats


def _create_alert(
    id_prescription_drug: str,
    key: str,
    alert_type: DrugAlertTypeEnum,
    alert_level: DrugAlertLevelEnum,
    text: str,
):
    return {
        "idPrescriptionDrug": id_prescription_drug,
        "key": key,
        "type": alert_type.value,
        "level": alert_level.value,
        "text": text,
    }


def _get_dose_conv(
    prescription_drug: PrescriptionDrug,
    drug_attributes: DrugAttributes,
    measure_unit_convert_factor: float,
):
    pd_frequency = (
        1
        if prescription_drug.frequency in [33, 44, 55, 66, 99]
        else prescription_drug.frequency
    )

    if drug_attributes != None and drug_attributes.division != None:
        return (
            numberutils.none2zero(prescription_drug.dose)
            * (
                measure_unit_convert_factor
                if measure_unit_convert_factor != None
                else 1
            )
            * numberutils.none2zero(pd_frequency)
        )

    return numberutils.none2zero(prescription_drug.doseconv) * numberutils.none2zero(
        pd_frequency
    )


def _get_dose_total(drug_list, exams: dict):
    dose_total = {}
    for item in drug_list:
        prescription_drug: PrescriptionDrug = item[0]
        drug_attributes: DrugAttributes = item[6]
        prescription_expire_date = item[10]
        expireDay = prescription_expire_date.day if prescription_expire_date else 0
        measure_unit_convert_factor = (
            item.measure_unit_convert_factor
            if item.measure_unit_convert_factor != None
            else 1
        )
        pd_dose_conv = _get_dose_conv(
            prescription_drug=prescription_drug,
            drug_attributes=drug_attributes,
            measure_unit_convert_factor=measure_unit_convert_factor,
        )

        if prescription_drug.frequency in [66]:
            # do not sum some types of frequency
            continue

        idDrugAgg = str(prescription_drug.idDrug) + "_" + str(expireDay)
        idDrugAggWeight = str(idDrugAgg) + "kg"

        # dose
        if idDrugAgg not in dose_total:
            dose_total[idDrugAgg] = {"value": pd_dose_conv, "count": 1}
        else:
            dose_total[idDrugAgg]["value"] += pd_dose_conv
            dose_total[idDrugAgg]["count"] += 1

        # dose / kg
        weight = numberutils.none2zero(exams["weight"])
        weight = weight if weight > 0 else 1
        doseWeight = round(pd_dose_conv / float(weight), 2)

        if idDrugAggWeight not in dose_total:
            dose_total[idDrugAggWeight] = {"value": doseWeight, "count": 1}
        else:
            dose_total[idDrugAggWeight]["value"] += doseWeight
            dose_total[idDrugAggWeight]["count"] += 1

    return dose_total


def _alert_ira(
    prescription_drug: PrescriptionDrug,
    drug: Drug,
    exams: dict,
    prescription_expire_date,
    dose_total: dict,
    dialysis: str,
    cn_data: dict,
):
    alert = _create_alert(
        id_prescription_drug=str(prescription_drug.id),
        key="",
        alert_type=DrugAlertTypeEnum.IRA,
        alert_level=DrugAlertLevelEnum.HIGH,
        text="",
    )

    if drug and "vanco" in drug.name.lower():
        expireDay = prescription_expire_date.day if prescription_expire_date else 0
        idDrugAgg = str(prescription_drug.idDrug) + "_" + str(expireDay)
        maxdose = dose_total[idDrugAgg]["value"] if idDrugAgg in dose_total else None
        ckd = _get_ckd_value(exams=exams)
        weight = exams["weight"]
        dialysis_ia_count = (
            cn_data.get("cn_stats", {}).get("dialysis", 0) if cn_data else 0
        )

        if (
            maxdose != None
            and ckd != None
            and weight != None
            and ckd > 0
            and weight > 0
        ):
            ira = maxdose / ckd / weight
            maxira = 0.6219

            if ira > maxira and dialysis is None and dialysis_ia_count == 0:
                alert[
                    "text"
                ] = f"""
                    Risco de desenvolvimento de Insuficiência Renal Aguda (IRA), já que o resultado do cálculo 
                    [dose diária de VANCOMICINA/TFG/peso] é superior a 0,6219. Caso o paciente esteja em diálise, 
                    desconsiderar. <a href="https://revista.ghc.com.br/index.php/cadernosdeensinoepesquisa/issue/view/3" target="_blank">Referência: CaEPS</a>
                """

                return alert

    return None


def _alert_max_dose(
    prescription_drug: PrescriptionDrug,
    drug_attributes: DrugAttributes,
    exams: dict,
    measure_unit_convert_factor: float,
):
    if not drug_attributes:
        return None
    pd_dose_conv = _get_dose_conv(
        prescription_drug=prescription_drug,
        drug_attributes=drug_attributes,
        measure_unit_convert_factor=measure_unit_convert_factor,
    )
    alert = _create_alert(
        id_prescription_drug=str(prescription_drug.id),
        key="",
        alert_type=DrugAlertTypeEnum.MAX_DOSE,
        alert_level=DrugAlertLevelEnum.HIGH,
        text="",
    )

    if drug_attributes.useWeight and prescription_drug.dose:
        weight = numberutils.none2zero(exams["weight"])
        weight = weight if weight > 0 else 1
        doseWeight = round(pd_dose_conv / float(weight), 2)

        if drug_attributes.maxDose and drug_attributes.maxDose < doseWeight:
            if numberutils.none2zero(exams["weight"]) == 0:
                alert["text"] = (
                    "A dose máxima registrada é por kg, mas o peso do paciente não está disponível. Favor preencher manualmente o peso."
                )
            else:
                alert[
                    "text"
                ] = f"""
                    Dose diária prescrita ({stringutils.strFormatBR(doseWeight)} {str(drug_attributes.idMeasureUnit)}/Kg) 
                    maior que a dose de alerta 
                    ({stringutils.strFormatBR(drug_attributes.maxDose)} {str(drug_attributes.idMeasureUnit)}/Kg) 
                    usualmente recomendada (considerada a dose diária independente da indicação).
                """

            return alert

    else:
        if drug_attributes.maxDose and drug_attributes.maxDose < pd_dose_conv:
            alert[
                "text"
            ] = f"""
                Dose diária prescrita ({str(pd_dose_conv)} {str(drug_attributes.idMeasureUnit)}) 
                maior que a dose de alerta ({str(drug_attributes.maxDose)} {str(drug_attributes.idMeasureUnit)}) 
                usualmente recomendada (considerada a dose diária independente da indicação).
            """

            return alert

    return None


def _alert_max_dose_total(
    prescription_drug: PrescriptionDrug,
    drug_attributes: DrugAttributes,
    exams: dict,
    prescription_expire_date,
    dose_total,
):
    if not drug_attributes:
        return None

    alert = _create_alert(
        id_prescription_drug=str(prescription_drug.id),
        key="",
        alert_type=DrugAlertTypeEnum.MAX_DOSE_PLUS,
        alert_level=DrugAlertLevelEnum.HIGH,
        text="",
    )

    expireDay = prescription_expire_date.day if prescription_expire_date else 0
    idDrugAgg = str(prescription_drug.idDrug) + "_" + str(expireDay)
    idDrugAggWeight = str(idDrugAgg) + "kg"
    if drug_attributes.useWeight and prescription_drug.dose:
        weight = numberutils.none2zero(exams["weight"])
        weight = weight if weight > 0 else 1

        if (
            drug_attributes.maxDose
            and idDrugAggWeight in dose_total
            and dose_total[idDrugAggWeight]["count"] > 1
            and drug_attributes.maxDose
            < numberutils.none2zero(dose_total[idDrugAggWeight]["value"])
        ):
            if numberutils.none2zero(exams["weight"]) == 0:
                alert["text"] = (
                    "A dose máxima registrada é por kg, mas o peso do paciente não está disponível. Favor preencher manualmente o peso."
                )
            else:
                alert[
                    "text"
                ] = f"""
                    Dose diária prescrita SOMADA (
                    {str(dose_total[idDrugAggWeight]["value"])} {str(drug_attributes.idMeasureUnit)}/Kg) maior 
                    que a dose de alerta (
                    {str(drug_attributes.maxDose)} {str(drug_attributes.idMeasureUnit)}/Kg) 
                    usualmente recomendada (Frequência "AGORA" não é considerada no cálculo)."
                """

            return alert

    else:
        if (
            drug_attributes.maxDose
            and idDrugAgg in dose_total
            and dose_total[idDrugAgg]["count"] > 1
            and drug_attributes.maxDose
            < numberutils.none2zero(dose_total[idDrugAgg]["value"])
        ):
            alert[
                "text"
            ] = f"""
                Dose diária prescrita SOMADA (
                {str(dose_total[idDrugAgg]["value"])} {str(drug_attributes.idMeasureUnit)}) maior que a 
                dose de alerta ({str(drug_attributes.maxDose)} {str(drug_attributes.idMeasureUnit)}) 
                usualmente recomendada (Frequência "AGORA" não é considerada no cálculo).
            """

            return alert

    return None


def _alert_max_time(
    prescription_drug: PrescriptionDrug, drug_attributes: DrugAttributes
):
    alert = _create_alert(
        id_prescription_drug=str(prescription_drug.id),
        key="",
        alert_type=DrugAlertTypeEnum.MAX_TIME,
        alert_level=DrugAlertLevelEnum.HIGH,
        text="",
    )

    if (
        drug_attributes
        and drug_attributes.maxTime
        and prescription_drug.period
        and prescription_drug.period > drug_attributes.maxTime
    ):
        alert[
            "text"
        ] = f"""
          Tempo de tratamento atual ({str(prescription_drug.period)} dias) maior que o tempo máximo de tratamento ( 
          {str(drug_attributes.maxTime)} dias) usualmente recomendado.
        """

        return alert

    return None


def _alert_pregnant(
    prescription_drug: PrescriptionDrug, drug_attributes: DrugAttributes, pregnant: bool
):
    alert = _create_alert(
        id_prescription_drug=str(prescription_drug.id),
        key="",
        alert_type=DrugAlertTypeEnum.PREGNANT,
        alert_level=DrugAlertLevelEnum.HIGH,
        text="",
    )

    if pregnant and drug_attributes != None:
        if drug_attributes.pregnant == "D" or drug_attributes.pregnant == "X":
            alert["text"] = (
                f"Paciente gestante com medicamento classificado como {drug_attributes.pregnant} prescrito. Avaliar manutenção deste medicamento com a equipe médica."
            )
            alert["level"] = (
                DrugAlertLevelEnum.HIGH.value
                if drug_attributes.pregnant == "X"
                else DrugAlertLevelEnum.MEDIUM.value
            )

            return alert

    return None


def _alert_lactating(
    prescription_drug: PrescriptionDrug,
    drug_attributes: DrugAttributes,
    lactating: bool,
):
    alert = _create_alert(
        id_prescription_drug=str(prescription_drug.id),
        key="",
        alert_type=DrugAlertTypeEnum.LACTATING,
        alert_level=DrugAlertLevelEnum.MEDIUM,
        text="",
    )

    if lactating and drug_attributes != None and drug_attributes.lactating == "3":
        alert["text"] = (
            f"""Paciente amamentando com medicamento classificado como Alto risco prescrito.
            Avaliar manutenção deste medicamento com a equipe médica ou cessação da amamentação."""
        )

        return alert

    return None


def _alert_allergy(prescription_drug: PrescriptionDrug):
    alert = _create_alert(
        id_prescription_drug=str(prescription_drug.id),
        key="",
        alert_type=DrugAlertTypeEnum.ALLERGY,
        alert_level=DrugAlertLevelEnum.HIGH,
        text="",
    )

    if prescription_drug.allergy == "S":
        alert["text"] = "Paciente alérgico a este medicamento."

        return alert

    return None


def _alert_tube(prescription_drug: PrescriptionDrug, drug_attributes: DrugAttributes):
    alert = _create_alert(
        id_prescription_drug=str(prescription_drug.id),
        key="",
        alert_type=DrugAlertTypeEnum.TUBE,
        alert_level=DrugAlertLevelEnum.HIGH,
        text="",
    )

    if drug_attributes and drug_attributes.tube and prescription_drug.tube:
        alert["text"] = (
            f"""Medicamento contraindicado via sonda ({stringutils.strNone(prescription_drug.route)})"""
        )

        return alert

    return None


def _alert_elderly(
    prescription_drug: PrescriptionDrug, drug_attributes: DrugAttributes, exams: dict
):
    if not drug_attributes or not exams:
        return None

    alert = _create_alert(
        id_prescription_drug=str(prescription_drug.id),
        key="",
        alert_type=DrugAlertTypeEnum.ELDERLY,
        alert_level=DrugAlertLevelEnum.LOW,
        text="",
    )

    if drug_attributes.elderly and exams["age"] > 60:
        alert[
            "text"
        ] = f"""
            Medicamento potencialmente inapropriado para idosos, independente das comorbidades do paciente.
        """

        return alert

    return None


def _alert_fasting(
    prescription_drug: PrescriptionDrug,
    drug_attributes: DrugAttributes,
    frequency: Frequency,
    schedules_fasting: List[str],
):
    if not drug_attributes or not frequency:
        return None

    alert = _create_alert(
        id_prescription_drug=str(prescription_drug.id),
        key="",
        alert_type=DrugAlertTypeEnum.FASTING,
        alert_level=DrugAlertLevelEnum.MEDIUM,
        text="",
    )

    if drug_attributes.fasting:
        # check frequency
        if frequency.fasting:
            return None

        # check schedules
        if (
            prescription_drug.interval != None
            and prescription_drug.interval in schedules_fasting
        ):
            return None

        alert[
            "text"
        ] = f"""
            O medicamento deve ser administrado em jejum, verificar horários de administração.
        """

        return alert

    return None


def _alert_platelets(
    prescription_drug: PrescriptionDrug, drug_attributes: DrugAttributes, exams: dict
):
    if not drug_attributes or not exams:
        return None

    if not drug_attributes.platelets:
        return None

    alert = _create_alert(
        id_prescription_drug=str(prescription_drug.id),
        key="",
        alert_type=DrugAlertTypeEnum.PLATELETS,
        alert_level=DrugAlertLevelEnum.HIGH,
        text="",
    )

    if (
        "plqt" in exams
        and exams["plqt"]["value"]
        and drug_attributes.platelets > exams["plqt"]["value"]
    ):
        alert[
            "text"
        ] = f"""
            Medicamento contraindicado para paciente com plaquetas ({str(exams["plqt"]["value"])} plaquetas/µL)
            abaixo de {str(drug_attributes.platelets)} plaquetas/µL.
        """

        return alert

    return None


def _alert_liver(
    prescription_drug: PrescriptionDrug, drug_attributes: DrugAttributes, exams: dict
):
    if not drug_attributes or not exams:
        return None

    if not drug_attributes.liver:
        return None

    alert = _create_alert(
        id_prescription_drug=str(prescription_drug.id),
        key="",
        alert_type=DrugAlertTypeEnum.LIVER,
        alert_level=DrugAlertLevelEnum.MEDIUM,
        text="",
    )

    tgp = (
        float(exams["tgp"]["value"]) if "tgp" in exams and exams["tgp"]["value"] else 0
    )
    tgo = (
        float(exams["tgo"]["value"]) if "tgo" in exams and exams["tgo"]["value"] else 0
    )

    if tgp > drug_attributes.liver or tgo > drug_attributes.liver:
        exam_name = "TGP" if tgp > tgo else "TGO"
        exam_value = tgp if tgp > tgo else tgo

        alert[
            "text"
        ] = f"""
            Avaliar se o medicamento já está com o ajuste adequado conforme a função hepática ou suspenso no caso de contraindicação, já que o paciente apresenta transaminase alterada. <br/>
            ({exam_name} {stringutils.strFormatBR(exam_value)} U/L).
        """

        return alert

    return None


def _alert_kidney(
    prescription_drug: PrescriptionDrug,
    drug_attributes: DrugAttributes,
    exams: dict,
    dialysis: str,
):
    if not drug_attributes or not exams:
        return None

    if not drug_attributes.kidney:
        return None

    alert = _create_alert(
        id_prescription_drug=str(prescription_drug.id),
        key="",
        alert_type=DrugAlertTypeEnum.KIDNEY,
        alert_level=DrugAlertLevelEnum.MEDIUM,
        text="",
    )

    if dialysis == "c":
        alert["text"] = (
            "Medicamento é contraindicado ou deve sofrer ajuste de posologia, já que o paciente está em diálise contínua."
        )

        return alert

    if dialysis == "x":
        alert["text"] = (
            "Medicamento é contraindicado ou deve sofrer ajuste de posologia, já que o paciente está em diálise estendida, também conhecida como SLED."
        )
        return alert

    if dialysis == "v":
        alert["text"] = (
            "Medicamento é contraindicado ou deve sofrer ajuste de posologia, já que o paciente está em diálise intermitente."
        )
        return alert

    if dialysis == "p":
        alert["text"] = (
            "Medicamento é contraindicado ou deve sofrer ajuste de posologia, já que o paciente está em diálise peritoneal."
        )
        return alert

    if exams["age"] > 17:
        ckd_value = _get_ckd_value(exams=exams)
        if ckd_value and drug_attributes.kidney > ckd_value:
            alert[
                "text"
            ] = f"""
                Avaliar se o medicamento já está com o ajuste adequado conforme a função renal ou suspenso no caso de contraindicação, já que a função renal do paciente (
                {str(ckd_value)} mL/min) está abaixo de {str(drug_attributes.kidney)} mL/min.
            """
            return alert

        # avaliando necessidade deste alerta
        # if not ckd_value:
        #     alert["text"] = (
        #         "Avaliar o monitoramento da função renal do paciente, pois trata-se de um medicamento que precisa ajuste conforme a função renal (sem registro de creatinina nos últimos 5 dias)."
        #     )
        #     return alert
    else:
        if (
            "swrtz2" in exams
            and exams["swrtz2"]["value"]
            and drug_attributes.kidney > exams["swrtz2"]["value"]
        ):
            alert[
                "text"
            ] = f"""
                Avaliar se o medicamento já está com o ajuste adequado conforme a função renal ou suspenso no caso de contraindicação, já que a função renal do paciente  
                ({str(exams["swrtz2"]["value"])} mL/min/1.73m²) está abaixo de 
                {str(drug_attributes.kidney)} mL/min. (Schwartz 2)
            """
            return alert

        if (
            "swrtz1" in exams
            and exams["swrtz1"]["value"]
            and drug_attributes.kidney > exams["swrtz1"]["value"]
        ):
            alert[
                "text"
            ] = f"""
                Avaliar se o medicamento já está com o ajuste adequado conforme a função renal ou suspenso no caso de contraindicação, já que a função renal do paciente  
                ({str(exams["swrtz1"]["value"])} mL/min/1.73m²) está abaixo de {str(drug_attributes.kidney)} 
                mL/min. (Schwartz 1)
            """
            return alert

    return None


def _filter_drug_list(drug_list):
    filtered_list = []
    valid_sources = [
        DrugTypeEnum.DRUG.value,
        DrugTypeEnum.SOLUTION.value,
        DrugTypeEnum.PROCEDURE.value,
    ]

    for item in drug_list:
        prescription_drug: PrescriptionDrug = item[0]

        if prescription_drug.source not in valid_sources:
            continue

        if prescription_drug.suspendedDate != None:
            continue

        filtered_list.append(item)

    return filtered_list


def _get_ckd_value(exams: dict):
    if "ckd21" in exams and exams["ckd21"]["value"]:
        return exams["ckd21"]["value"]

    if "ckd" in exams and exams["ckd"]["value"]:
        return exams["ckd"]["value"]

    return None
