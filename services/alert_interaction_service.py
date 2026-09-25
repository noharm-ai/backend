"""Service to analyze interactions between drugs in a prescription."""

from datetime import datetime, timedelta
from typing import List

from sqlalchemy import text

from models.enums import DrugAlertLevelEnum, DrugTypeEnum, FrequencyEnum
from models.main import Allergy, Drug, DrugAttributes, Substance, db
from models.prescription import PrescriptionDrug
from utils import dateutils, examutils, prescriptionutils, stringutils

RELATION_KINDS = ["it", "dt", "dm", "iy", "sl", "rx"]


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
        drug_from = build_relation_item(item=item, is_cpoe=is_cpoe)

        for compare_item in filtered_list:
            if item[0].id == compare_item[0].id:
                continue

            drug_to = build_relation_item(item=compare_item, is_cpoe=is_cpoe)

            if get_period_mismatch(
                drug_from=drug_from, drug_to=drug_to, is_cpoe=is_cpoe
            ):
                continue

            overlap_drugs.append({"from": drug_from, "to": drug_to})

        for a in allergies:
            overlap_drugs.append({"from": {**drug_from, "rx": True}, "to": a})

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

    for kind in RELATION_KINDS:
        stats[kind] = 0

    for drug in overlap_drugs:
        drug_from = drug["from"]
        drug_to = drug["to"]

        for kind in RELATION_KINDS:
            key = f"""{drug_from["sctid"]}-{drug_to["sctid"]}-{kind}"""
            invert_key = f"""{drug_to["sctid"]}-{drug_from["sctid"]}-{kind}"""

            if key not in active_relations:
                continue

            if not all(
                rule["passed"]
                for rule in evaluate_kind_rules(
                    kind=kind, drug_from=drug_from, drug_to=drug_to
                )
            ):
                continue

            if is_cpoe:
                uniq_key = key
                uniq_invert_key = invert_key
            else:
                uniq_key = f"""{key}-{drug_from["expireDate"]}"""
                uniq_invert_key = f"""{invert_key}-{drug_from["expireDate"]}"""

            if (
                uniq_key not in unique_relations
                and uniq_invert_key not in unique_relations
            ):
                stats[kind] += 1
                unique_relations[uniq_key] = 1
                unique_relations[uniq_invert_key] = 1

            alert = build_alert(
                kind=kind,
                relation=active_relations[key],
                drug_from=drug_from,
                drug_to=drug_to,
            )

            for id in alert["ids"]:
                alert_obj = {
                    "idPrescriptionDrug": id,
                    "key": key,
                    "type": kind,
                    "level": alert["level"],
                    "relation": drug_to["id"],
                    "text": alert["text"],
                }

                if id in alerts:
                    # avoid alert repetition
                    text_array = [a["text"] for a in alerts[id]]
                    if alert["text"] not in text_array:
                        alerts[id].append(alert_obj)
                else:
                    alerts[id] = [alert_obj]

    return {"alerts": alerts, "stats": stats}


def _resolve_expire_date(prescription_date: datetime, expire_date: datetime):
    """expire date used to compare drugs (drugs without one last 24h or until today)"""
    if expire_date is not None:
        return expire_date

    if prescription_date.date() >= datetime.now().date():
        return prescription_date + timedelta(hours=24)

    return datetime.today()


def build_relation_item(item, is_cpoe: bool) -> dict:
    """Builds the comparable representation of a prescribed drug
    (row from find_drugs_by_prescription)"""
    prescription_drug: PrescriptionDrug = item[0]
    drug: Drug = item[1]
    prescription_date = item[13]
    expire_date = _resolve_expire_date(
        prescription_date=prescription_date, expire_date=item[10]
    )

    return {
        "id": str(prescription_drug.id),
        "drug": drug.name,
        "sctid": drug.sctid,
        "intravenous": (
            prescription_drug.intravenous
            if prescription_drug.intravenous != None
            else False
        ),
        "group": _get_solution_group_key(pd=prescription_drug, is_cpoe=is_cpoe),
        "prescriptionDate": prescription_date.isoformat(),
        "expireDate": expire_date.isoformat(),
        "frequency": prescription_drug.frequency,
        "rx": False,
        "interval": prescription_drug.interval,
    }


def get_period_mismatch(drug_from: dict, drug_to: dict, is_cpoe: bool) -> str | None:
    """Checks if two prescribed drugs are compared at all.
    Returns a user-friendly reason when they are not, None when they are"""
    start1 = datetime.fromisoformat(drug_from["prescriptionDate"]).date()
    end1 = datetime.fromisoformat(drug_from["expireDate"]).date()
    start2 = datetime.fromisoformat(drug_to["prescriptionDate"]).date()
    end2 = datetime.fromisoformat(drug_to["expireDate"]).date()

    if is_cpoe:
        # period overlap
        if not (start1 <= end2 and start2 <= end1):
            return (
                "Os períodos de vigência não se sobrepõem "
                f"({drug_from['drug']}: {start1:%d/%m/%Y} a {end1:%d/%m/%Y}; "
                f"{drug_to['drug']}: {start2:%d/%m/%Y} a {end2:%d/%m/%Y}). "
                "Em CPOE, só são comparados itens com vigências sobrepostas."
            )
    else:
        # same expire date
        if end1 != end2:
            return (
                "Os itens têm datas de vigência diferentes "
                f"({drug_from['drug']}: {end1:%d/%m/%Y}; "
                f"{drug_to['drug']}: {end2:%d/%m/%Y}). "
                "Só são comparados itens com a mesma data de vigência."
            )

    return None


def _yes_no(value) -> str:
    return "sim" if value else "não"


def evaluate_kind_rules(kind: str, drug_from: dict, drug_to: dict) -> list[dict]:
    """Rules a relation kind requires to raise an alert from drug_from to drug_to.
    An alert is raised only when every rule passes"""
    rules = []

    # rx rules
    if kind == "rx":
        rules.append(
            {
                "rule": "rx_allergy",
                "passed": bool(drug_from["rx"]),
                "message": "Reatividade cruzada só é avaliada entre um item "
                "prescrito e uma alergia do paciente.",
            }
        )
    else:
        rules.append(
            {
                "rule": "not_allergy",
                "passed": not drug_from["rx"],
                "message": "Este tipo de relação só é avaliado entre dois itens "
                "prescritos (não se aplica a alergias).",
            }
        )

    # iy must have intravenous route
    if kind == "iy":
        rules.append(
            {
                "rule": "intravenous",
                "passed": bool(drug_from["intravenous"] and drug_to["intravenous"]),
                "message": "Os dois itens precisam ser intravenosos "
                f"({drug_from['drug']}: {_yes_no(drug_from['intravenous'])}; "
                f"{drug_to['drug']}: {_yes_no(drug_to['intravenous'])}).",
            }
        )

    # sl must be in the same group
    if kind == "sl":
        rules.append(
            {
                "rule": "same_solution_group",
                "passed": drug_from["group"] is not None
                and drug_from["group"] == drug_to["group"],
                "message": "Os dois itens precisam estar no mesmo grupo de solução "
                f"({drug_from['drug']}: {drug_from['group'] or 'sem grupo'}; "
                f"{drug_to['drug']}: {drug_to['group'] or 'sem grupo'}).",
            }
        )

    # dm cant have frequency 66
    if kind == "dm":
        rules.append(
            {
                "rule": "not_now_frequency",
                "passed": drug_from["frequency"] != FrequencyEnum.NOW.value
                and drug_to["frequency"] != FrequencyEnum.NOW.value,
                "message": "Nenhum dos itens pode ter frequência 'agora' (66), "
                "pois dose única não é duplicidade "
                f"({drug_from['drug']}: {drug_from['frequency']}; "
                f"{drug_to['drug']}: {drug_to['frequency']}).",
            }
        )

    if kind in ["dm", "dt", "iy"] and not drug_from["rx"]:
        # this types must overlap considering the time too
        start1 = datetime.fromisoformat(drug_from["prescriptionDate"])
        end1 = datetime.fromisoformat(drug_from["expireDate"])

        if end1 < start1:
            end1 = start1 + timedelta(minutes=1)

        start2 = datetime.fromisoformat(drug_to["prescriptionDate"])
        end2 = datetime.fromisoformat(drug_to["expireDate"])

        if end2 < start2:
            end2 = start2 + timedelta(minutes=1)

        rules.append(
            {
                "rule": "time_overlap",
                "passed": dateutils.date_overlap(
                    start1=start1, end1=end1, start2=start2, end2=end2
                ),
                "message": "As vigências precisam se sobrepor considerando também "
                "o horário "
                f"({drug_from['drug']}: {start1:%d/%m/%Y %H:%M} a {end1:%d/%m/%Y %H:%M}; "
                f"{drug_to['drug']}: {start2:%d/%m/%Y %H:%M} a {end2:%d/%m/%Y %H:%M}).",
            }
        )

    return rules


def build_alert(kind: str, relation: dict, drug_from: dict, drug_to: dict) -> dict:
    """Builds the alert raised by an active relation that passed its kind rules.
    level_notes explain every adjustment made to the relation level"""
    level_notes = []

    if relation["level"] != None:
        alert_level = relation["level"]
    else:
        alert_level = DrugAlertLevelEnum.LOW.value
        level_notes.append("A relação não tem nível cadastrado: assumido 'low'.")

    # dm with frequency SN (33) has its level reduced
    if kind == "dm" and (
        drug_from["frequency"] == FrequencyEnum.SN.value
        or drug_to["frequency"] == FrequencyEnum.SN.value
    ):
        reduced_level = _reduce_alert_level(alert_level)
        level_notes.append(
            "Um dos itens tem frequência 'se necessário' (33): nível reduzido "
            f"de '{alert_level}' para '{reduced_level}'."
        )
        alert_level = reduced_level

    alert_text = examutils.typeRelations[kind] + ": "
    alert_text += stringutils.strNone(relation["text"])

    if kind in ["iy", "it"]:
        alert_text += f"""- {drug_from["drug"]} (Horários: {prescriptionutils.timeValue(drug_from["interval"]) if drug_from["interval"] else "--"})
                        - {drug_to["drug"]} (Horários: {prescriptionutils.timeValue(drug_to["interval"]) if drug_to["interval"] else "--"})
                    """

        if kind == "iy":
            if _has_interval_intersection(
                interval1=drug_from["interval"],
                interval2=drug_to["interval"],
            ):
                level_notes.append(
                    "Os itens têm horários de administração coincidentes: nível "
                    f"definido como '{DrugAlertLevelEnum.MEDIUM.value}'."
                )
                alert_level = DrugAlertLevelEnum.MEDIUM.value
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

    return {
        "level": alert_level,
        "text": alert_text,
        "ids": ids,
        "level_notes": level_notes,
    }


def _reduce_alert_level(alert_level: str) -> str:
    """reduce alert level by one step (high -> medium -> low)"""
    if alert_level == DrugAlertLevelEnum.HIGH.value:
        return DrugAlertLevelEnum.MEDIUM.value

    return DrugAlertLevelEnum.LOW.value


def _has_interval_intersection(interval1: str, interval2: str) -> bool:
    """check if there is an intersection between intervals"""
    if not interval1 or not interval2:
        return False

    list1 = interval1.split()
    list2 = interval2.split()

    # Find the intersection of the two lists
    intersection = set(list1) & set(list2)

    # check if the intersection elements have a valid number
    for element in intersection:
        try:
            float(element.replace(":", ""))
            return True
        except ValueError:
            continue

    # no numeric intersection
    return False


def _filter_drug_list(drug_list):
    return [item for item in drug_list if get_ineligibility_reason(item=item) is None]


def get_ineligibility_reason(item) -> str | None:
    """Checks if a prescribed drug takes part in the interaction analysis.
    Returns a user-friendly reason when it does not, None when it does"""
    valid_sources = [
        DrugTypeEnum.DRUG.value,
        DrugTypeEnum.SOLUTION.value,
        DrugTypeEnum.PROCEDURE.value,
    ]

    prescription_drug: PrescriptionDrug = item[0]
    drug_attributes: DrugAttributes = item[6]
    drug: Drug = item[1]

    if prescription_drug.source not in valid_sources:
        return (
            f"A origem '{prescription_drug.source}' não é analisada "
            f"(somente {', '.join(valid_sources)})."
        )

    if prescription_drug.suspendedDate != None:
        return "O item está suspenso."

    if drug == None:
        return "O item não está vinculado a um medicamento cadastrado."

    if drug.sctid == None:
        return "O medicamento não tem substância definida."

    if (
        drug_attributes != None
        and drug_attributes.whiteList
        and not prescription_drug.source == DrugTypeEnum.SOLUTION.value
    ):
        return (
            "O medicamento está marcado como 'sem validação' (lista branca) "
            "neste segmento."
        )

    return None


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
