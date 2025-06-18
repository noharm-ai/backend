"""Service to analyze interactions between drugs in a prescription."""

from datetime import datetime
from typing import List

from sqlalchemy import text

from models.prescription import PrescriptionDrug
from models.main import db, Drug, Substance, Allergy, DrugAttributes
from models.enums import DrugTypeEnum, DrugAlertLevelEnum, FrequencyEnum
from utils import examutils, stringutils, prescriptionutils


# analyze interactions between drugs.
# drug_list (PrescriptionDrug.findByPrescription)
def find_relations(drug_list, id_patient: int, is_cpoe: bool):
    """
    Find interactions between drugs in a prescription.
    :param drug_list: List of drugs in the prescription.
    :param id_patient: ID of the patient.
    :param is_cpoe: Boolean indicating if the prescription is CPOE.
    :return: Dictionary with alerts, stats, and list of interactions."""

    filtered_list = _filter_drug_list(drug_list=drug_list)
    allergies = _get_allergies(id_patient=id_patient)
    overlap_drugs = []

    for item in filtered_list:
        prescription_drug: PrescriptionDrug = item[0]
        drug: Drug = item[1]
        prescription_date = item[13]
        prescription_expire_date = item[10] if item[10] != None else datetime.today()

        for compare_item in filtered_list:
            cp_prescription_drug: PrescriptionDrug = compare_item[0]
            cp_drug: Drug = compare_item[1]
            cp_prescription_date = compare_item[13]
            cp_prescription_expire_date = (
                compare_item[10] if compare_item[10] != None else datetime.today()
            )

            if prescription_drug.id == cp_prescription_drug.id:
                continue

            if is_cpoe:
                # period overlap
                if not (
                    (prescription_date.date() <= cp_prescription_expire_date.date())
                    and (cp_prescription_date.date() <= prescription_expire_date.date())
                ):
                    continue
            else:
                # same expire date
                if not (
                    prescription_expire_date.date()
                    == cp_prescription_expire_date.date()
                ):
                    continue

            overlap_drugs.append(
                {
                    "from": {
                        "id": str(prescription_drug.id),
                        "drug": drug.name,
                        "sctid": drug.sctid,
                        "intravenous": (
                            prescription_drug.intravenous
                            if prescription_drug.intravenous != None
                            else False
                        ),
                        "group": _get_solution_group_key(
                            pd=prescription_drug, is_cpoe=is_cpoe
                        ),
                        "expireDate": prescription_expire_date.isoformat(),
                        "frequency": prescription_drug.frequency,
                        "rx": False,
                        "interval": prescriptionutils.timeValue(
                            prescription_drug.interval
                        ),
                    },
                    "to": {
                        "id": str(cp_prescription_drug.id),
                        "drug": cp_drug.name,
                        "sctid": cp_drug.sctid,
                        "intravenous": (
                            cp_prescription_drug.intravenous
                            if cp_prescription_drug.intravenous != None
                            else False
                        ),
                        "group": _get_solution_group_key(
                            pd=cp_prescription_drug, is_cpoe=is_cpoe
                        ),
                        "expireDate": cp_prescription_expire_date.isoformat(),
                        "frequency": cp_prescription_drug.frequency,
                        "rx": False,
                        "interval": prescriptionutils.timeValue(
                            cp_prescription_drug.interval
                        ),
                    },
                }
            )

        for a in allergies:
            overlap_drugs.append(
                {
                    "from": {
                        "id": str(prescription_drug.id),
                        "drug": drug.name,
                        "sctid": drug.sctid,
                        "intravenous": (
                            prescription_drug.intravenous
                            if prescription_drug.intravenous != None
                            else False
                        ),
                        "group": _get_solution_group_key(
                            pd=prescription_drug, is_cpoe=is_cpoe
                        ),
                        "expireDate": prescription_expire_date.isoformat(),
                        "frequency": prescription_drug.frequency,
                        "rx": True,
                        "interval": prescriptionutils.timeValue(
                            prescription_drug.interval
                        ),
                    },
                    "to": a,
                }
            )

    if len(overlap_drugs) == 0:
        return {"alerts": {}, "list": {}, "stats": {}}

    uniq_overlap_keys = []
    for d in overlap_drugs:
        key = f"""({d["from"]["sctid"]},{d["to"]["sctid"]})"""
        if key not in uniq_overlap_keys:
            uniq_overlap_keys.append(key)

    active_relations = _get_active_relations(uniq_overlap_keys)

    alerts = {}
    stats = {}
    unique_relations = {}
    kinds = ["it", "dt", "dm", "iy", "sl", "rx"]

    for kind in kinds:
        stats[kind] = 0

    for drug in overlap_drugs:
        drug_from = drug["from"]
        drug_to = drug["to"]

        for kind in kinds:
            key = f"""{drug_from["sctid"]}-{drug_to["sctid"]}-{kind}"""
            invert_key = f"""{drug_to["sctid"]}-{drug_from["sctid"]}-{kind}"""

            # iy must have intravenous route
            if kind == "iy" and (
                not drug_from["intravenous"] or not drug_to["intravenous"]
            ):
                continue

            # sl must be in the same group
            if kind == "sl" and (
                drug_from["group"] != drug_to["group"] or drug_from["group"] == None
            ):
                continue

            # dm cant have frequency 66
            if kind == "dm" and (
                drug_from["frequency"] == FrequencyEnum.NOW.value
                or drug_to["frequency"] == FrequencyEnum.NOW.value
            ):
                continue

            # rx rules
            if kind == "rx":
                if not drug_from["rx"]:
                    continue
            else:
                if drug_from["rx"]:
                    continue

            if key in active_relations:
                if is_cpoe:
                    uniq_key = key
                    uniq_invert_key = invert_key
                else:
                    uniq_key = f"""{key}-{drug_from["expireDate"]}"""
                    uniq_invert_key = f"""{invert_key}-{drug_from["expireDate"]}"""

                if (
                    not uniq_key in unique_relations
                    and not uniq_invert_key in unique_relations
                ):
                    stats[kind] += 1
                    unique_relations[uniq_key] = 1
                    unique_relations[uniq_invert_key] = 1

                alert_text = examutils.typeRelations[kind] + ": "
                alert_text += stringutils.strNone(active_relations[key]["text"])

                if kind == "iy":
                    alert_text += f"""- {drug_from["drug"]} (Horários: {drug_from['interval']}) 
                        - {drug_to["drug"]} (Horários: {drug_to['interval']})
                    """
                else:
                    alert_text += (
                        " ("
                        + stringutils.strNone(drug_from["drug"])
                        + " e "
                        + stringutils.strNone(drug_to["drug"])
                        + ")"
                    )

                if kind == "dm":
                    # one way
                    ids = [drug_from["id"]]
                else:
                    # both ways
                    ids = [drug_from["id"], drug_to["id"]]

                for id in ids:
                    alert_obj = {
                        "idPrescriptionDrug": id,
                        "key": key,
                        "type": kind,
                        "level": (
                            active_relations[key]["level"]
                            if active_relations[key]["level"] != None
                            else DrugAlertLevelEnum.LOW.value
                        ),
                        "relation": drug_to["id"],
                        "text": alert_text,
                    }

                    if id in alerts:
                        # avoid alert repetition
                        text_array = [a["text"] for a in alerts[id]]
                        if alert_text not in text_array:
                            alerts[id].append(alert_obj)
                    else:
                        alerts[id] = [alert_obj]

    return {"alerts": alerts, "stats": stats}


def _filter_drug_list(drug_list):
    filtered_list = []
    valid_sources = [
        DrugTypeEnum.DRUG.value,
        DrugTypeEnum.SOLUTION.value,
        DrugTypeEnum.PROCEDURE.value,
    ]

    for item in drug_list:
        prescription_drug: PrescriptionDrug = item[0]
        drug_attributes: DrugAttributes = item[6]
        drug: Drug = item[1]

        if prescription_drug.source not in valid_sources:
            continue

        if prescription_drug.suspendedDate != None:
            continue

        if drug == None or drug.sctid == None:
            continue

        if (
            drug_attributes != None
            and drug_attributes.whiteList
            and not prescription_drug.source == DrugTypeEnum.SOLUTION.value
        ):
            continue

        filtered_list.append(item)

    return filtered_list


def _get_solution_group_key(pd: PrescriptionDrug, is_cpoe: bool):
    if is_cpoe:
        if pd.cpoe_group:
            return f"{pd.idPrescription}-{pd.cpoe_group}"
    else:
        if pd.solutionGroup:
            return f"{pd.idPrescription}-{pd.solutionGroup}"

    return None


def _get_allergies(id_patient: int):
    allergies = (
        db.session.query(Substance.id, Substance.name)
        .select_from(Allergy)
        .join(Drug, Allergy.idDrug == Drug.id)
        .join(Substance, Substance.id == Drug.sctid)
        .filter(Allergy.idPatient == id_patient)
        .filter(Allergy.active == True)
        .group_by(Substance.id, Substance.name)
        .all()
    )

    results = []
    for a in allergies:
        if a.id != None:
            results.append(
                {
                    "id": None,
                    "drug": a.name,
                    "sctid": a.id,
                    "intravenous": False,
                    "group": None,
                    "frequency": None,
                    "rx": True,
                    "interval": "-",
                }
            )

    return results


def _get_active_relations(uniq_overlap_keys: List[str]):
    query = text(
        f"""
        with cruzamento as (
            select * from (values {",".join(uniq_overlap_keys)}) AS t (sctida, sctidb)
        )
        select
            r.sctida,
            r.sctidb,
            r.tprelacao as "kind",
            r.texto as "text",
            r.nivel as "level"
        from 
            public.relacao r 
            inner join cruzamento c on (r.sctida = c.sctida and r.sctidb = c.sctidb)
        where 
	        r.ativo = true
    """
    )
    active_relations = {}

    for item in db.session.execute(query).all():
        key = f"{item.sctida}-{item.sctidb}-{item.kind}"
        active_relations[key] = {
            "sctida": item.sctida,
            "sctidb": item.sctidb,
            "kind": item.kind,
            "text": item.text,
            "level": item.level,
        }

    return active_relations
