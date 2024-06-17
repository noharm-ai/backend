from datetime import datetime
from sqlalchemy import or_, and_

from models.prescription import PrescriptionDrug, Allergy
from models.main import db, Drug, Relation, Substance
from models.enums import DrugTypeEnum
from routes.utils import typeRelations, strNone


def find_relations(drug_list, id_patient: int, is_cpoe: bool):
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
                if not (prescription_expire_date == cp_prescription_expire_date):
                    continue

            overlap_drugs.append(
                {
                    "from": {
                        "id": prescription_drug.id,
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
                        "rx": False,
                    },
                    "to": {
                        "id": cp_prescription_drug.id,
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
                        "rx": False,
                    },
                }
            )

        for a in allergies:
            overlap_drugs.append(
                {
                    "from": {
                        "id": prescription_drug.id,
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
                        "rx": True,
                    },
                    "to": a,
                }
            )

    if len(overlap_drugs) == 0:
        return {"alerts": {}, "list": {}, "stats": {}}

    query = db.session.query(Relation).filter(Relation.active == True)

    query = query.filter(
        or_(
            and_(
                Relation.sctida == i["from"]["sctid"],
                Relation.sctidb == i["to"]["sctid"],
            )
            for i in overlap_drugs
        )
    )

    active_relations = {}

    for item in query.all():
        key = f"{item.sctida}-{item.sctidb}-{item.kind}"
        active_relations[key] = {
            "sctida": item.sctida,
            "sctidb": item.sctidb,
            "kind": item.kind,
            "text": item.text,
        }

    alerts = {}
    relations = {}
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
            if kind == "sl" and (drug_from["group"] != drug_to["group"]):
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

                alert = typeRelations[kind] + ": "
                alert += (
                    strNone(active_relations[key]["text"])
                    + " ("
                    + strNone(drug_from["drug"])
                    + " e "
                    + strNone(drug_to["drug"])
                    + ")"
                )

                relation = {
                    "key": key,
                    "kind": kind,
                    "to": drug_to["id"],
                }

                if kind == "dm":
                    # one way
                    ids = [drug_from["id"]]
                else:
                    # both ways
                    ids = [drug_from["id"], drug_to["id"]]

                for id in ids:
                    if id in alerts:
                        relations[id].append(relation)
                        if alert not in alerts[id]:
                            alerts[id].append(alert)
                    else:
                        alerts[id] = [alert]
                        relations[id] = [relation]

    return {"alerts": alerts, "list": relations, "stats": stats}


def _filter_drug_list(drug_list):
    filtered_list = []
    valid_sources = [
        DrugTypeEnum.DRUG.value,
        DrugTypeEnum.SOLUTION.value,
        DrugTypeEnum.PROCEDURE.value,
    ]

    for item in drug_list:
        prescription_drug: PrescriptionDrug = item[0]
        drug: Drug = item[1]
        if prescription_drug.source not in valid_sources:
            continue

        if prescription_drug.suspendedDate != None:
            continue

        if drug == None or drug.sctid == None:
            continue

        filtered_list.append(item)

    return filtered_list


def _get_solution_group_key(pd: PrescriptionDrug, is_cpoe: bool):
    if is_cpoe:
        return f"{pd.idPrescription}-{pd.cpoe_group}"
    else:
        return f"{pd.idPrescription}-{pd.solutionGroup}"


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
                    "rx": True,
                }
            )

    return results
