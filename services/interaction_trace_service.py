"""Service: drug interaction tracing (explains why an interaction alert was or
was not raised between two items of a prescription)"""

from datetime import datetime

from sqlalchemy import and_, or_

from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from models.main import Allergy, Drug, Relation, Substance, User, db
from models.prescription import Prescription
from models.requests.interaction_trace_request import InteractionTraceRequest
from services import alert_interaction_service, prescription_view_service
from utils import examutils, status

_DRUG_PAIR_KINDS = [k for k in alert_interaction_service.RELATION_KINDS if k != "rx"]


@has_permission(Permission.MAINTAINER)
def trace_interaction(request_data: InteractionTraceRequest, user_context: User = None):
    """Re-runs the interaction analysis of a prescription for a pair of items and
    explains, step by step, why an alert was or was not raised"""

    context = prescription_view_service.get_interaction_evaluation_context(
        id_prescription=request_data.idPrescription, user_context=user_context
    )
    prescription: Prescription = context["prescription"]
    drug_list = context["drug_list"]
    is_cpoe = context["is_cpoe"]

    allergies = alert_interaction_service._get_allergies(
        id_patient=prescription.idPatient
    )

    result = {
        "idPrescription": str(prescription.id),
        "evaluatedAt": datetime.now().isoformat(),
        "isCpoe": bool(is_cpoe),
        "agg": bool(prescription.agg),
        "items": [_item_option(item=item) for item in drug_list],
        "allergies": [{"sctid": str(a["sctid"]), "name": a["drug"]} for a in allergies],
        "allergiesWithoutSubstance": _get_allergies_without_substance(
            id_patient=prescription.idPatient
        ),
        "trace": None,
    }

    if request_data.idPrescriptionDrugFrom is None:
        return result

    if (request_data.idPrescriptionDrugTo is None) == (
        request_data.sctidAllergy is None
    ):
        raise ValidationError(
            "Informe o segundo item: outro item da prescrição ou uma alergia",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )

    item_from = _find_item(drug_list, request_data.idPrescriptionDrugFrom)

    if request_data.sctidAllergy is not None:
        allergy = next(
            (a for a in allergies if str(a["sctid"]) == str(request_data.sctidAllergy)),
            None,
        )
        if allergy is None:
            raise ValidationError(
                "Alergia não encontrada para este paciente",
                "errors.invalidParams",
                status.HTTP_400_BAD_REQUEST,
            )

        result["trace"] = _trace_allergy(
            item_from=item_from, allergy=allergy, is_cpoe=is_cpoe
        )
    else:
        if request_data.idPrescriptionDrugTo == request_data.idPrescriptionDrugFrom:
            raise ValidationError(
                "Selecione dois itens diferentes",
                "errors.invalidParams",
                status.HTTP_400_BAD_REQUEST,
            )

        item_to = _find_item(drug_list, request_data.idPrescriptionDrugTo)
        result["trace"] = _trace_drug_pair(
            item_from=item_from, item_to=item_to, is_cpoe=is_cpoe
        )

    return result


def _find_item(drug_list, id_prescription_drug: int):
    """Finds a prescribed item among the items analyzed for the prescription"""
    for item in drug_list:
        if item[0].id == id_prescription_drug:
            return item

    raise ValidationError(
        "Item não encontrado nesta prescrição",
        "errors.invalidParams",
        status.HTTP_400_BAD_REQUEST,
    )


def _item_option(item) -> dict:
    """Selectable prescribed item, flagged when it is left out of the analysis"""
    prescription_drug = item[0]
    drug = item[1]
    substance = item[11]
    reason = alert_interaction_service.get_ineligibility_reason(item=item)

    return {
        "idPrescriptionDrug": str(prescription_drug.id),
        "idPrescription": str(prescription_drug.idPrescription),
        "drug": drug.name if drug else None,
        "substance": substance.name if substance else None,
        "sctid": str(drug.sctid) if drug and drug.sctid else None,
        "source": prescription_drug.source,
        "suspended": prescription_drug.suspendedDate is not None,
        "eligible": reason is None,
        "ineligibilityReason": reason,
    }


def _get_allergies_without_substance(id_patient: int) -> list[str]:
    """Active allergies that can never raise cross reactivity (no substance)"""
    rows = (
        db.session.query(Allergy.drugName, Drug.name)
        .outerjoin(Drug, Allergy.idDrug == Drug.id)
        .filter(Allergy.idPatient == id_patient)
        .filter(Allergy.active == True)
        .filter(Drug.sctid == None)
        .all()
    )

    return sorted({r[1] or r[0] or "--" for r in rows})


def _trace_side(item) -> dict:
    """Item details relevant to the analysis, even when it is left out of it"""
    option = _item_option(item=item)
    prescription_drug = item[0]

    details = {
        **option,
        "intravenous": None,
        "group": None,
        "frequency": prescription_drug.frequency,
        "interval": prescription_drug.interval,
        "prescriptionDate": item[13].isoformat() if item[13] else None,
        "expireDate": None,
    }

    return details


def _trace_drug_pair(item_from, item_to, is_cpoe: bool) -> dict:
    """Explains the analysis between two prescribed items (both directions)"""
    side_from = _trace_side(item=item_from)
    side_to = _trace_side(item=item_to)
    checks = _eligibility_checks(sides=[side_from, side_to])
    compared = all(c["passed"] for c in checks)

    kinds = []
    if compared:
        drug_from = alert_interaction_service.build_relation_item(
            item=item_from, is_cpoe=is_cpoe
        )
        drug_to = alert_interaction_service.build_relation_item(
            item=item_to, is_cpoe=is_cpoe
        )
        _fill_relation_details(side=side_from, relation_item=drug_from)
        _fill_relation_details(side=side_to, relation_item=drug_to)

        mismatch = alert_interaction_service.get_period_mismatch(
            drug_from=drug_from, drug_to=drug_to, is_cpoe=is_cpoe
        )
        checks.append(
            {
                "rule": "period",
                "passed": mismatch is None,
                "message": mismatch
                or (
                    "Os períodos de vigência se sobrepõem (CPOE)."
                    if is_cpoe
                    else "Os itens têm a mesma data de vigência."
                ),
            }
        )
        compared = mismatch is None

    relations = _get_registered_relations(
        sctid_a=item_from[1].sctid if item_from[1] else None,
        sctid_b=item_to[1].sctid if item_to[1] else None,
    )

    if compared:
        for kind in _DRUG_PAIR_KINDS:
            kinds.append(
                {
                    "kind": kind,
                    "label": examutils.typeRelations[kind],
                    "directions": [
                        _evaluate_direction(kind, drug_from, drug_to, relations),
                        _evaluate_direction(kind, drug_to, drug_from, relations),
                    ],
                }
            )

    return _finish_trace(
        side_from=side_from,
        side_to=side_to,
        is_allergy=False,
        checks=checks,
        compared=compared,
        relations=relations,
        kinds=kinds,
    )


def _trace_allergy(item_from, allergy: dict, is_cpoe: bool) -> dict:
    """Explains the cross reactivity analysis between a prescribed item and one
    of the patient's allergies (evaluated only from the item to the allergy)"""
    side_from = _trace_side(item=item_from)
    side_to = {
        "idPrescriptionDrug": None,
        "drug": allergy["drug"],
        "substance": allergy["drug"],
        "sctid": str(allergy["sctid"]),
        "source": "Alergia",
        "eligible": True,
        "ineligibilityReason": None,
    }
    checks = _eligibility_checks(sides=[side_from])
    compared = all(c["passed"] for c in checks)

    kinds = []
    relations = _get_registered_relations(
        sctid_a=item_from[1].sctid if item_from[1] else None,
        sctid_b=allergy["sctid"],
    )

    if compared:
        drug_from = alert_interaction_service.build_relation_item(
            item=item_from, is_cpoe=is_cpoe
        )
        _fill_relation_details(side=side_from, relation_item=drug_from)
        drug_from = {**drug_from, "rx": True}

        kinds.append(
            {
                "kind": "rx",
                "label": examutils.typeRelations["rx"],
                "directions": [
                    _evaluate_direction("rx", drug_from, allergy, relations),
                ],
            }
        )

    return _finish_trace(
        side_from=side_from,
        side_to=side_to,
        is_allergy=True,
        checks=checks,
        compared=compared,
        relations=relations,
        kinds=kinds,
    )


def _fill_relation_details(side: dict, relation_item: dict):
    """Copies the values the analysis actually compared into the item details"""
    side.update(
        {
            "intravenous": relation_item["intravenous"],
            "group": relation_item["group"],
            "prescriptionDate": relation_item["prescriptionDate"],
            "expireDate": relation_item["expireDate"],
        }
    )


def _eligibility_checks(sides: list[dict]) -> list[dict]:
    """One check per prescribed item: is it part of the analysis at all"""
    return [
        {
            "rule": "eligible",
            "passed": side["eligible"],
            "message": (
                f"{side['drug'] or '--'}: participa da análise de interações."
                if side["eligible"]
                else f"{side['drug'] or '--'}: {side['ineligibilityReason']}"
            ),
        }
        for side in sides
    ]


def _get_registered_relations(sctid_a, sctid_b) -> list[dict]:
    """Every relation registered between two substances, in both directions,
    active or not"""
    if sctid_a is None or sctid_b is None:
        return []

    rows = (
        db.session.query(Relation)
        .filter(
            or_(
                and_(Relation.sctida == sctid_a, Relation.sctidb == sctid_b),
                and_(Relation.sctida == sctid_b, Relation.sctidb == sctid_a),
            )
        )
        .all()
    )

    names = {
        str(s.id): s.name
        for s in db.session.query(Substance)
        .filter(Substance.id.in_([sctid_a, sctid_b]))
        .all()
    }

    return [
        {
            "sctida": str(r.sctida),
            "sctidb": str(r.sctidb),
            "substanceA": names.get(str(r.sctida)),
            "substanceB": names.get(str(r.sctidb)),
            "kind": r.kind,
            "label": examutils.typeRelations.get(r.kind, r.kind),
            "active": bool(r.active),
            "level": r.level,
            "text": r.text,
        }
        for r in sorted(rows, key=lambda r: (r.kind, str(r.sctida)))
    ]


def _evaluate_direction(
    kind: str, drug_from: dict, drug_to: dict, relations: list[dict]
) -> dict:
    """Evaluates one relation kind from drug_from to drug_to, exactly as
    find_relations does, keeping every intermediate decision"""
    relation = next(
        (
            r
            for r in relations
            if r["kind"] == kind
            and r["sctida"] == str(drug_from["sctid"])
            and r["sctidb"] == str(drug_to["sctid"])
        ),
        None,
    )

    direction = {
        "from": drug_from["drug"],
        "to": drug_to["drug"],
        "relation": relation,
        "rules": [],
        "alerted": False,
        "alert": None,
    }

    if relation is None:
        direction["message"] = "Não há relação cadastrada neste sentido."
        return direction

    if not relation["active"]:
        direction["message"] = "A relação está cadastrada, porém inativa."
        return direction

    direction["rules"] = alert_interaction_service.evaluate_kind_rules(
        kind=kind, drug_from=drug_from, drug_to=drug_to
    )

    failed = [r for r in direction["rules"] if not r["passed"]]
    if failed:
        direction["message"] = "Há relação ativa, mas uma regra não foi atendida."
        return direction

    alert = alert_interaction_service.build_alert(
        kind=kind, relation=relation, drug_from=drug_from, drug_to=drug_to
    )
    names_by_id = {
        drug_from["id"]: drug_from["drug"],
        drug_to["id"]: drug_to["drug"],
    }

    direction["alerted"] = True
    direction["message"] = "Alerta gerado."
    direction["alert"] = {
        "level": alert["level"],
        "text": alert["text"],
        "levelNotes": alert["level_notes"],
        "shownOn": [names_by_id[i] for i in alert["ids"] if i is not None],
    }

    return direction


def _finish_trace(
    side_from: dict,
    side_to: dict,
    is_allergy: bool,
    checks: list[dict],
    compared: bool,
    relations: list[dict],
    kinds: list[dict],
) -> dict:
    """Assembles the trace with a one-line summary of the outcome"""
    alerted_labels = [
        k["label"] for k in kinds if any(d["alerted"] for d in k["directions"])
    ]
    kinds_evaluated = {k["kind"] for k in kinds}

    if not compared:
        failed = next(c for c in checks if not c["passed"])
        summary = f"Nenhum alerta: os itens não são comparados. {failed['message']}"
    elif alerted_labels:
        summary = f"Alerta gerado: {', '.join(alerted_labels)}."
    elif not relations:
        summary = (
            "Nenhum alerta: não há relação cadastrada entre as substâncias "
            f"{side_from['substance'] or side_from['drug']} e "
            f"{side_to['substance'] or side_to['drug']}."
        )
    elif not any(r["active"] and r["kind"] in kinds_evaluated for r in relations):
        summary = (
            "Nenhum alerta: há relação cadastrada entre as substâncias, porém "
            "inativa ou de um tipo que não se aplica a este par."
        )
    else:
        summary = (
            "Nenhum alerta: há relação ativa entre as substâncias, mas as regras "
            "do tipo de relação não foram atendidas (veja o detalhe abaixo)."
        )

    notes = []
    if is_allergy and any(
        r["sctida"] == side_to["sctid"] and r["kind"] == "rx" for r in relations
    ):
        notes.append(
            "Há relação de reatividade cruzada cadastrada no sentido "
            "alergia → medicamento. Só o sentido medicamento → alergia é avaliado."
        )

    return {
        "from": side_from,
        "to": side_to,
        "isAllergy": is_allergy,
        "compared": compared,
        "alerted": len(alerted_labels) > 0,
        "summary": summary,
        "notes": notes,
        "checks": checks,
        "relations": relations,
        "kinds": kinds,
    }
