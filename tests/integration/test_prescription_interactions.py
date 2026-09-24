"""Integration tests for the drug-interaction and cross-reactivity alerts that
``GET /prescriptions/<id>`` raises (``alert_interaction_service``).

Two prescribed drugs raise an alert when ``public.relacao`` holds an active row
for their substance pair. The relation kind decides what is checked:

* ``it`` (interação medicamentosa) and ``dt`` (duplicidade terapêutica) —
  the pair alone;
* ``dm`` (duplicidade medicamentosa) — same, but the alert lands on one drug
  only, and a single ("agora") dose never counts as a duplication;
* ``iy`` (incompatibilidade em Y) — both drugs must be intravenous, and the
  alert is escalated to ``medium`` when their schedules actually meet;
* ``sl`` (incompatibilidade em solução) — both drugs must sit in the same
  solution group;
* ``rx`` (reatividade cruzada) — the pair is a prescribed drug against a
  substance the *patient* is registered as allergic to.

``tests/unit/test_alerts_interaction.py`` covers the same kinds against a
stubbed relation table. What is only reachable from here is the wiring around
it: the query that selects the active relations, the allergy lookup, the
eligibility rules that decide which prescribed drugs are compared at all
(source, suspension, missing substance, white list), and the alert reaching the
prescription payload the client actually reads.

Substance and drug ids are >= 90000 and rows in ``public.relacao`` are deleted
by the fixture, so nothing here outlives the test.
"""

import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from models.enums import DrugTypeEnum
from tests.conftest import session, session_commit
from tests.utils import utils_test_prescription

# ids >= 90000 are wiped by tests/conftest.py::_cleanup
_SUBSTANCE_A = (90101, "ZZTest Substância A")
_SUBSTANCE_B = (90102, "ZZTest Substância B")
_SUBSTANCE_ALLERGEN = (90103, "ZZTest Substância Alérgeno")

_DRUG_A = (90101, "ZZTest Medicamento A")
_DRUG_B = (90102, "ZZTest Medicamento B")
_DRUG_ALLERGEN = (90103, "ZZTest Medicamento Alérgeno")
# a drug with no substance can never be matched against a relation
_DRUG_NO_SUBSTANCE = (90104, "ZZTest Medicamento Sem Substância")

_SEED_PATIENT = 1
# department 3 maps to segment 2, the seeded CPOE segment
_SEGMENT_CPOE = 2

_RELATION_TEXT = "ZZTest texto da relação"

# demo.presmed recomputes "intravenosa" on insert from the prescribed route and
# the schema's map-iv memory, which the seed does not define. A drug is only
# intravenous, and so only eligible for an "iy" alert, when both exist.
_IV_ROUTE = "EV"


def _create_drug(id_drug: int, name: str, sctid: int | None) -> None:
    session.execute(
        text(
            "INSERT INTO demo.medicamento "
            "(fkmedicamento, fkhospital, nome, sctid, created_at) "
            "VALUES (:id, 1, :name, :sctid, now())"
        ),
        {"id": id_drug, "name": name, "sctid": sctid},
    )


def _add_relation(sctid_a: int, sctid_b: int, kind: str, level: str, active=True):
    """Register an active relation between two substances."""
    session.execute(
        text(
            "INSERT INTO public.relacao "
            "(sctida, sctidb, tprelacao, texto, nivel, ativo, update_at, update_by) "
            "VALUES (:a, :b, :kind, :text, :level, :active, now(), 1)"
        ),
        {
            "a": sctid_a,
            "b": sctid_b,
            "kind": kind,
            "text": _RELATION_TEXT,
            "level": level,
            "active": active,
        },
    )
    session_commit()


def _clear_owned_rows():
    """Remove every row this module creates, in dependency order."""
    session.execute(text("DELETE FROM public.relacao WHERE sctida >= 90000"))
    session.execute(text("DELETE FROM demo.alergia WHERE fkmedicamento >= 90000"))
    session.execute(text("DELETE FROM demo.medatributos WHERE fkmedicamento >= 90000"))
    session.execute(text("DELETE FROM demo.medicamento WHERE fkmedicamento >= 90000"))
    session.execute(text("DELETE FROM public.substancia WHERE sctid >= 90000"))
    session.execute(text("DELETE FROM demo.memoria WHERE tipo = 'map-iv'"))
    session_commit()


@pytest.fixture
def seed_substances_and_drugs():
    """Substances and drugs the relations point at, plus the relation cleanup.

    The seed catalogue carries no sctid at all, so drug-interaction analysis
    skips every seeded drug — these rows are what makes it run.
    """
    # public.relacao is not part of the session-wide cleanup, so a run that
    # died before its teardown must not leak a relation into the next test
    _clear_owned_rows()

    for sctid, name in (_SUBSTANCE_A, _SUBSTANCE_B, _SUBSTANCE_ALLERGEN):
        session.execute(
            text(
                "INSERT INTO public.substancia (sctid, nome, link, ativo) "
                "VALUES (:id, :name, '', true)"
            ),
            {"id": sctid, "name": name},
        )

    _create_drug(_DRUG_A[0], _DRUG_A[1], _SUBSTANCE_A[0])
    _create_drug(_DRUG_B[0], _DRUG_B[1], _SUBSTANCE_B[0])
    _create_drug(_DRUG_ALLERGEN[0], _DRUG_ALLERGEN[1], _SUBSTANCE_ALLERGEN[0])
    _create_drug(_DRUG_NO_SUBSTANCE[0], _DRUG_NO_SUBSTANCE[1], None)

    session.execute(
        text(
            "INSERT INTO demo.memoria (tipo, valor, update_at, update_by) "
            "VALUES ('map-iv', CAST(:value AS json), now(), 1)"
        ),
        {"value": json.dumps([_IV_ROUTE])},
    )
    session_commit()

    yield

    _clear_owned_rows()


def _prescription_with(client, headers, drugs: list[dict], cpoe=False):
    """Create a prescription carrying the given drugs and return its payload.

    ``drugs`` entries are kwargs for
    ``utils_test_prescription.create_prescription_drug`` minus the ids.
    """
    prescription = utils_test_prescription.create_basic_prescription(cpoe=cpoe)

    # create_basic_prescription adds two seeded drugs; they have no sctid, so
    # they are invisible to the interaction analysis and cannot interfere
    base_id = int(f"{prescription.id}010")
    for offset, drug in enumerate(drugs):
        utils_test_prescription.create_prescription_drug(
            id=base_id + offset,
            idPrescription=prescription.id,
            **drug,
        )

    response = client.get(f"/prescriptions/{prescription.id}", headers=headers)
    assert response.status_code == 200

    data = response.get_json()["data"]
    data["_drugIds"] = [base_id + offset for offset in range(len(drugs))]
    return data


def _alerts_of(payload: dict, id_prescription_drug: int) -> list[dict]:
    """Every alert attached to one prescribed drug.

    Raises when the drug is missing from the payload, so an assertion of "no
    alerts" cannot pass just because the drug was never rendered.
    """
    for item in payload["prescription"] + payload["solution"] + payload["procedures"]:
        if item["idPrescriptionDrug"] == str(id_prescription_drug):
            return item["alertsComplete"]

    raise AssertionError(
        f"prescribed drug {id_prescription_drug} is not in the prescription payload"
    )


def _count(payload: dict, kind: str) -> int:
    """How many alerts of one kind the prescription reports.

    The counters are absent altogether when no two items were eligible to be
    compared, which for these assertions means the same as zero.
    """
    return payload["alertStats"]["interactions"].get(kind, 0)


# --- the relation query --------------------------------------------------------


def test_an_active_relation_raises_the_interaction_alert(
    client, analyst_headers, seed_substances_and_drugs
):
    """Two drugs whose substances are related alert each other."""
    _add_relation(_SUBSTANCE_A[0], _SUBSTANCE_B[0], "it", "high")

    payload = _prescription_with(
        client,
        analyst_headers,
        [{"idDrug": _DRUG_A[0]}, {"idDrug": _DRUG_B[0]}],
    )
    id_a, id_b = payload["_drugIds"]

    assert _count(payload, "it") == 1

    alert = _alerts_of(payload, id_a)[0]
    assert alert["type"] == "it"
    assert alert["level"] == "high"
    assert _RELATION_TEXT in alert["text"]
    assert "Interação Medicamentosa" in alert["text"]

    # both drugs carry it, each pointing at the other
    assert _alerts_of(payload, id_b)[0]["type"] == "it"


def test_an_inactive_relation_raises_nothing(
    client, analyst_headers, seed_substances_and_drugs
):
    """A relation retired by the curators stops alerting."""
    _add_relation(_SUBSTANCE_A[0], _SUBSTANCE_B[0], "it", "high", active=False)

    payload = _prescription_with(
        client,
        analyst_headers,
        [{"idDrug": _DRUG_A[0]}, {"idDrug": _DRUG_B[0]}],
    )

    assert _count(payload, "it") == 0
    assert _alerts_of(payload, payload["_drugIds"][0]) == []


def test_drugs_without_a_relation_raise_nothing(
    client, analyst_headers, seed_substances_and_drugs
):
    """Substances with no row in relacao are simply not compared."""
    payload = _prescription_with(
        client,
        analyst_headers,
        [{"idDrug": _DRUG_A[0]}, {"idDrug": _DRUG_B[0]}],
    )

    assert _count(payload, "it") == 0


def test_a_relation_is_not_raised_against_the_drug_itself(
    client, analyst_headers, seed_substances_and_drugs
):
    """A single prescribed drug has nothing to be compared with."""
    _add_relation(_SUBSTANCE_A[0], _SUBSTANCE_A[0], "it", "high")

    payload = _prescription_with(client, analyst_headers, [{"idDrug": _DRUG_A[0]}])

    assert _count(payload, "it") == 0


def test_the_relation_level_falls_back_to_low(
    client, analyst_headers, seed_substances_and_drugs
):
    """A curated relation with no level is treated as a low alert."""
    _add_relation(_SUBSTANCE_A[0], _SUBSTANCE_B[0], "it", None)

    payload = _prescription_with(
        client,
        analyst_headers,
        [{"idDrug": _DRUG_A[0]}, {"idDrug": _DRUG_B[0]}],
    )

    assert _alerts_of(payload, payload["_drugIds"][0])[0]["level"] == "low"


# --- which prescribed drugs are eligible ---------------------------------------


def test_a_suspended_drug_is_not_compared(
    client, analyst_headers, seed_substances_and_drugs
):
    """A suspended item is no longer in use, so it cannot interact."""
    _add_relation(_SUBSTANCE_A[0], _SUBSTANCE_B[0], "it", "high")

    payload = _prescription_with(
        client,
        analyst_headers,
        [
            {"idDrug": _DRUG_A[0]},
            {"idDrug": _DRUG_B[0], "suspendedDate": datetime.now()},
        ],
    )

    assert _count(payload, "it") == 0


def test_a_drug_without_a_substance_is_not_compared(
    client, analyst_headers, seed_substances_and_drugs
):
    """Relations are keyed by substance, so an unmapped drug never matches."""
    _add_relation(_SUBSTANCE_A[0], _SUBSTANCE_B[0], "it", "high")

    payload = _prescription_with(
        client,
        analyst_headers,
        [{"idDrug": _DRUG_A[0]}, {"idDrug": _DRUG_NO_SUBSTANCE[0]}],
    )

    assert _count(payload, "it") == 0


def test_a_diet_item_is_not_compared(
    client, analyst_headers, seed_substances_and_drugs
):
    """Only drugs, solutions and procedures take part in the analysis."""
    _add_relation(_SUBSTANCE_A[0], _SUBSTANCE_B[0], "it", "high")

    payload = _prescription_with(
        client,
        analyst_headers,
        [
            {"idDrug": _DRUG_A[0]},
            {"idDrug": _DRUG_B[0], "source": DrugTypeEnum.DIET.value},
        ],
    )

    assert _count(payload, "it") == 0


def test_a_procedure_is_compared(
    client, analyst_headers, seed_substances_and_drugs
):
    """Procedures carry substances too and are part of the analysis."""
    _add_relation(_SUBSTANCE_A[0], _SUBSTANCE_B[0], "it", "high")

    payload = _prescription_with(
        client,
        analyst_headers,
        [
            {"idDrug": _DRUG_A[0]},
            {"idDrug": _DRUG_B[0], "source": DrugTypeEnum.PROCEDURE.value},
        ],
    )

    assert _count(payload, "it") == 1


def test_a_white_listed_drug_is_not_compared(
    client, analyst_headers, seed_substances_and_drugs
):
    """A drug on the schema's white list is excluded from the analysis."""
    _add_relation(_SUBSTANCE_A[0], _SUBSTANCE_B[0], "it", "high")
    session.execute(
        text(
            "INSERT INTO demo.medatributos "
            "(fkmedicamento, idsegmento, linhabranca, update_at, update_by) "
            "VALUES (:id, 1, true, now(), 1) "
            "ON CONFLICT (fkmedicamento, idsegmento) "
            "DO UPDATE SET linhabranca = true"
        ),
        {"id": _DRUG_B[0]},
    )
    session_commit()

    payload = _prescription_with(
        client,
        analyst_headers,
        [{"idDrug": _DRUG_A[0]}, {"idDrug": _DRUG_B[0]}],
    )

    assert _count(payload, "it") == 0


def test_a_white_listed_solution_is_still_compared(
    client, analyst_headers, seed_substances_and_drugs
):
    """The white list does not silence solutions: an ISL still has to be seen."""
    _add_relation(_SUBSTANCE_A[0], _SUBSTANCE_B[0], "it", "high")
    session.execute(
        text(
            "INSERT INTO demo.medatributos "
            "(fkmedicamento, idsegmento, linhabranca, update_at, update_by) "
            "VALUES (:id, 1, true, now(), 1) "
            "ON CONFLICT (fkmedicamento, idsegmento) "
            "DO UPDATE SET linhabranca = true"
        ),
        {"id": _DRUG_B[0]},
    )
    session_commit()

    payload = _prescription_with(
        client,
        analyst_headers,
        [
            {"idDrug": _DRUG_A[0]},
            {
                "idDrug": _DRUG_B[0],
                "source": DrugTypeEnum.SOLUTION.value,
                "solutionGroup": 1,
            },
        ],
    )

    assert _count(payload, "it") == 1


# --- kind-specific rules -------------------------------------------------------


def test_a_duplication_alert_lands_on_one_drug_only(
    client, analyst_headers, seed_substances_and_drugs
):
    """``dm`` is one-way: the second prescription of the pair is the duplicate."""
    _add_relation(_SUBSTANCE_A[0], _SUBSTANCE_B[0], "dm", "high")

    payload = _prescription_with(
        client,
        analyst_headers,
        [{"idDrug": _DRUG_A[0]}, {"idDrug": _DRUG_B[0]}],
    )
    id_a, id_b = payload["_drugIds"]

    assert _count(payload, "dm") == 1
    assert [a["type"] for a in _alerts_of(payload, id_a)] == ["dm"]
    assert _alerts_of(payload, id_b) == []


def test_a_single_dose_is_not_a_duplication(
    client, analyst_headers, seed_substances_and_drugs
):
    """An "agora" dose (frequency 66) is a one-off, never a duplication."""
    _add_relation(_SUBSTANCE_A[0], _SUBSTANCE_B[0], "dm", "high")

    payload = _prescription_with(
        client,
        analyst_headers,
        [
            {"idDrug": _DRUG_A[0]},
            {"idDrug": _DRUG_B[0], "frequency": 66.0, "idFrequency": "66"},
        ],
    )

    assert _count(payload, "dm") == 0


def test_incompatibility_in_y_requires_both_drugs_intravenous(
    client, analyst_headers, seed_substances_and_drugs
):
    """``iy`` is about mixing in the line, so an oral drug cannot raise it."""
    _add_relation(_SUBSTANCE_A[0], _SUBSTANCE_B[0], "iy", "high")

    payload = _prescription_with(
        client,
        analyst_headers,
        [
            {"idDrug": _DRUG_A[0], "route": _IV_ROUTE},
            {"idDrug": _DRUG_B[0], "route": "VO"},
        ],
    )

    assert _count(payload, "iy") == 0


def test_incompatibility_in_y_alerts_two_intravenous_drugs(
    client, analyst_headers, seed_substances_and_drugs
):
    """Two IV drugs with no shared schedule keep the curated level."""
    _add_relation(_SUBSTANCE_A[0], _SUBSTANCE_B[0], "iy", "low")

    payload = _prescription_with(
        client,
        analyst_headers,
        [
            {"idDrug": _DRUG_A[0], "route": _IV_ROUTE, "interval": "06:00"},
            {"idDrug": _DRUG_B[0], "route": _IV_ROUTE, "interval": "18:00"},
        ],
    )

    assert _count(payload, "iy") == 1

    alert = _alerts_of(payload, payload["_drugIds"][0])[0]
    assert alert["level"] == "low"
    # the schedules are spelled out so the pharmacist can re-plan them
    assert "Horários" in alert["text"]


def test_incompatibility_in_y_is_escalated_by_a_shared_schedule(
    client, analyst_headers, seed_substances_and_drugs
):
    """Two IV drugs given at the same hour actually meet: level goes to medium."""
    _add_relation(_SUBSTANCE_A[0], _SUBSTANCE_B[0], "iy", "low")

    payload = _prescription_with(
        client,
        analyst_headers,
        [
            {"idDrug": _DRUG_A[0], "route": _IV_ROUTE, "interval": "06:00 18:00"},
            {"idDrug": _DRUG_B[0], "route": _IV_ROUTE, "interval": "12:00 18:00"},
        ],
    )

    assert _alerts_of(payload, payload["_drugIds"][0])[0]["level"] == "medium"


def test_a_shared_non_numeric_schedule_does_not_escalate(
    client, analyst_headers, seed_substances_and_drugs
):
    """Only a real clock time means the two infusions meet.

    Two drugs both marked "ACM" (a criterio medico) share a schedule *string*,
    but nothing says they are given together, so the curated level stands.
    """
    _add_relation(_SUBSTANCE_A[0], _SUBSTANCE_B[0], "iy", "low")

    payload = _prescription_with(
        client,
        analyst_headers,
        [
            {"idDrug": _DRUG_A[0], "route": _IV_ROUTE, "interval": "ACM"},
            {"idDrug": _DRUG_B[0], "route": _IV_ROUTE, "interval": "ACM"},
        ],
    )

    assert _count(payload, "iy") == 1
    assert _alerts_of(payload, payload["_drugIds"][0])[0]["level"] == "low"


def test_a_drug_without_a_schedule_does_not_escalate(
    client, analyst_headers, seed_substances_and_drugs
):
    """An unscheduled drug cannot be shown to meet the other one."""
    _add_relation(_SUBSTANCE_A[0], _SUBSTANCE_B[0], "iy", "low")

    payload = _prescription_with(
        client,
        analyst_headers,
        [
            {"idDrug": _DRUG_A[0], "route": _IV_ROUTE, "interval": "06:00"},
            {"idDrug": _DRUG_B[0], "route": _IV_ROUTE, "interval": None},
        ],
    )

    assert _alerts_of(payload, payload["_drugIds"][0])[0]["level"] == "low"


def test_solution_incompatibility_needs_the_same_group(
    client, analyst_headers, seed_substances_and_drugs
):
    """``sl`` compares what is mixed in one bag, so the group must match."""
    _add_relation(_SUBSTANCE_A[0], _SUBSTANCE_B[0], "sl", "high")

    payload = _prescription_with(
        client,
        analyst_headers,
        [
            {
                "idDrug": _DRUG_A[0],
                "source": DrugTypeEnum.SOLUTION.value,
                "solutionGroup": 1,
            },
            {
                "idDrug": _DRUG_B[0],
                "source": DrugTypeEnum.SOLUTION.value,
                "solutionGroup": 2,
            },
        ],
    )

    assert _count(payload, "sl") == 0


def test_solution_incompatibility_alerts_inside_one_group(
    client, analyst_headers, seed_substances_and_drugs
):
    """Same bag, related substances: the ISL alert is raised."""
    _add_relation(_SUBSTANCE_A[0], _SUBSTANCE_B[0], "sl", "high")

    payload = _prescription_with(
        client,
        analyst_headers,
        [
            {
                "idDrug": _DRUG_A[0],
                "source": DrugTypeEnum.SOLUTION.value,
                "solutionGroup": 1,
            },
            {
                "idDrug": _DRUG_B[0],
                "source": DrugTypeEnum.SOLUTION.value,
                "solutionGroup": 1,
            },
        ],
    )

    assert _count(payload, "sl") == 1


# --- the allergy cross-check ---------------------------------------------------


def _register_allergy(id_patient: int, id_drug: int, active=True) -> None:
    session.execute(
        text(
            "INSERT INTO demo.alergia "
            "(fkpessoa, fkmedicamento, ativo, created_at, created_by) "
            "VALUES (:id_patient, :id_drug, :active, now(), 1)"
        ),
        {"id_patient": id_patient, "id_drug": id_drug, "active": active},
    )
    session_commit()


def test_a_cross_reactivity_alert_reads_the_patient_allergies(
    client, analyst_headers, seed_substances_and_drugs
):
    """``rx`` compares a prescribed drug against what the patient reacts to.

    The allergen is not prescribed: it comes from the patient's allergy list.
    """
    _register_allergy(_SEED_PATIENT, _DRUG_ALLERGEN[0])
    _add_relation(_SUBSTANCE_A[0], _SUBSTANCE_ALLERGEN[0], "rx", "high")

    payload = _prescription_with(client, analyst_headers, [{"idDrug": _DRUG_A[0]}])

    assert _count(payload, "rx") == 1

    alert = _alerts_of(payload, payload["_drugIds"][0])[0]
    assert alert["type"] == "rx"
    assert "Reatividade Cruzada" in alert["text"]
    # the allergen is named so the pharmacist knows what the reaction is to
    assert _SUBSTANCE_ALLERGEN[1] in alert["text"]


def test_an_inactive_allergy_is_not_cross_checked(
    client, analyst_headers, seed_substances_and_drugs
):
    """An allergy the team has retracted stops producing alerts."""
    _register_allergy(_SEED_PATIENT, _DRUG_ALLERGEN[0], active=False)
    _add_relation(_SUBSTANCE_A[0], _SUBSTANCE_ALLERGEN[0], "rx", "high")

    payload = _prescription_with(client, analyst_headers, [{"idDrug": _DRUG_A[0]}])

    assert _count(payload, "rx") == 0


def test_an_allergy_without_a_relation_raises_no_cross_reactivity(
    client, analyst_headers, seed_substances_and_drugs
):
    """Cross reactivity is curated: an allergy alone does not imply it."""
    _register_allergy(_SEED_PATIENT, _DRUG_ALLERGEN[0])

    payload = _prescription_with(client, analyst_headers, [{"idDrug": _DRUG_A[0]}])

    assert _count(payload, "rx") == 0


def test_a_drug_relation_is_not_raised_as_cross_reactivity(
    client, analyst_headers, seed_substances_and_drugs
):
    """``rx`` only ever compares against allergies, never two prescribed drugs."""
    _add_relation(_SUBSTANCE_A[0], _SUBSTANCE_B[0], "rx", "high")

    payload = _prescription_with(
        client,
        analyst_headers,
        [{"idDrug": _DRUG_A[0]}, {"idDrug": _DRUG_B[0]}],
    )

    assert _count(payload, "rx") == 0


# --- what the payload reports --------------------------------------------------


def test_the_prescription_alert_level_follows_the_relation(
    client, analyst_headers, seed_substances_and_drugs
):
    """A high interaction raises the whole prescription's alert level."""
    _add_relation(_SUBSTANCE_A[0], _SUBSTANCE_B[0], "it", "high")

    payload = _prescription_with(
        client,
        analyst_headers,
        [{"idDrug": _DRUG_A[0]}, {"idDrug": _DRUG_B[0]}],
    )

    assert payload["alertStats"]["level"] == "high"


def test_two_relations_on_the_same_pair_are_counted_separately(
    client, analyst_headers, seed_substances_and_drugs
):
    """A pair may be both a therapeutic duplication and an interaction."""
    _add_relation(_SUBSTANCE_A[0], _SUBSTANCE_B[0], "it", "high")
    _add_relation(_SUBSTANCE_A[0], _SUBSTANCE_B[0], "dt", "low")

    payload = _prescription_with(
        client,
        analyst_headers,
        [{"idDrug": _DRUG_A[0]}, {"idDrug": _DRUG_B[0]}],
    )

    assert _count(payload, "it") == 1
    assert _count(payload, "dt") == 1

    assert sorted(a["type"] for a in _alerts_of(payload, payload["_drugIds"][0])) == [
        "dt",
        "it",
    ]


# --- the prescription window --------------------------------------------------


def _open_ended_prescription_with_both_drugs(date: datetime) -> int:
    """Create a prescription with a NULL dtvigencia carrying both drugs.

    ``utils_test_prescription.create_prescription`` always fills the expire
    date, so the row is written as SQL to keep it open-ended.
    """
    id_prescription = utils_test_prescription.test_counters["id_prescription"]
    admission_number = utils_test_prescription.test_counters["admission_number"]
    utils_test_prescription.test_counters["id_prescription"] += 1
    utils_test_prescription.test_counters["admission_number"] += 1

    session.execute(
        text(
            "INSERT INTO demo.prescricao "
            "(fkprescricao, nratendimento, fkpessoa, fkhospital, fksetor, "
            " idsegmento, dtprescricao, dtvigencia, status, update_at, update_by) "
            "VALUES (:id, :admission, :id_patient, 1, 1, 1, :date, NULL, '0', "
            " now(), 1)"
        ),
        {
            "id": id_prescription,
            "admission": admission_number,
            "id_patient": _SEED_PATIENT,
            "date": date,
        },
    )
    session_commit()

    base_id = int(f"{id_prescription}010")
    for offset, id_drug in enumerate((_DRUG_A[0], _DRUG_B[0])):
        utils_test_prescription.create_prescription_drug(
            id=base_id + offset,
            idPrescription=id_prescription,
            idDrug=id_drug,
        )

    expire = session.execute(
        text("SELECT dtvigencia FROM demo.prescricao WHERE fkprescricao = :id"),
        {"id": id_prescription},
    ).scalar()
    assert expire is None, "the prescription must stay open-ended for these tests"

    return id_prescription


def test_a_prescription_without_an_expire_date_is_still_compared(
    client, analyst_headers, seed_substances_and_drugs
):
    """An open-ended prescription is assumed to run for a day, not skipped.

    ``prescricao.expire`` is nullable and real integrations do leave it empty;
    the analysis must still pair the drugs instead of dropping the whole
    prescription.
    """
    _add_relation(_SUBSTANCE_A[0], _SUBSTANCE_B[0], "dt", "high")

    id_prescription = _open_ended_prescription_with_both_drugs(datetime.now())

    response = client.get(f"/prescriptions/{id_prescription}", headers=analyst_headers)

    assert response.status_code == 200
    assert _count(response.get_json()["data"], "dt") == 1


def test_an_old_open_ended_prescription_is_still_compared(
    client, analyst_headers, seed_substances_and_drugs
):
    """One written before today is treated as running up to now, not forward."""
    _add_relation(_SUBSTANCE_A[0], _SUBSTANCE_B[0], "dt", "high")

    id_prescription = _open_ended_prescription_with_both_drugs(
        datetime.now() - timedelta(days=2)
    )

    response = client.get(f"/prescriptions/{id_prescription}", headers=analyst_headers)

    assert response.status_code == 200
    assert _count(response.get_json()["data"], "dt") == 1


# --- CPOE ----------------------------------------------------------------------


def _create_cpoe_solution(
    id: int, id_prescription: int, id_drug: int, cpoe_nrseq: int
) -> None:
    """Insert a CPOE solution item straight through demo.presmed.

    demo.presmed derives cpoe_grupo from cpoe_nrseq on insert, and the column
    is not on the PrescriptionDrug model, so the row is written as SQL.
    """
    session.execute(
        text(
            "INSERT INTO demo.presmed "
            "(fkpresmed, fkprescricao, fkmedicamento, fkunidademedida, fkfrequencia, "
            " idsegmento, dose, origem, via, cpoe_nrseq, status) "
            "VALUES (:id, :id_prescription, :id_drug, 'mg', '1x', :id_segment, 100, "
            " :source, 'VO', :cpoe_nrseq, '0')"
        ),
        {
            "id": id,
            "id_prescription": id_prescription,
            "id_drug": id_drug,
            "id_segment": _SEGMENT_CPOE,
            "source": DrugTypeEnum.SOLUTION.value,
            "cpoe_nrseq": cpoe_nrseq,
        },
    )
    session_commit()


def test_cpoe_reads_the_solution_group_from_the_cpoe_group(
    client, analyst_headers, seed_substances_and_drugs
):
    """In CPOE the bag is identified by cpoe_grupo, not by slagrupamento."""
    _add_relation(_SUBSTANCE_A[0], _SUBSTANCE_B[0], "sl", "high")

    prescription = utils_test_prescription.create_basic_prescription(cpoe=True)
    base_id = int(f"{prescription.id}010")
    # the same cpoe_nrseq on both items puts them in one bag
    _create_cpoe_solution(base_id, prescription.id, _DRUG_A[0], cpoe_nrseq=base_id)
    _create_cpoe_solution(base_id + 1, prescription.id, _DRUG_B[0], cpoe_nrseq=base_id)

    response = client.get(f"/prescriptions/{prescription.id}", headers=analyst_headers)

    assert response.status_code == 200
    assert _count(response.get_json()["data"], "sl") == 1


def test_cpoe_items_in_different_bags_do_not_alert(
    client, analyst_headers, seed_substances_and_drugs
):
    """Two CPOE items in separate bags are not mixed and raise no ISL."""
    _add_relation(_SUBSTANCE_A[0], _SUBSTANCE_B[0], "sl", "high")

    prescription = utils_test_prescription.create_basic_prescription(cpoe=True)
    base_id = int(f"{prescription.id}010")
    _create_cpoe_solution(base_id, prescription.id, _DRUG_A[0], cpoe_nrseq=base_id)
    _create_cpoe_solution(
        base_id + 1, prescription.id, _DRUG_B[0], cpoe_nrseq=base_id + 1
    )

    response = client.get(f"/prescriptions/{prescription.id}", headers=analyst_headers)

    assert response.status_code == 200
    assert _count(response.get_json()["data"], "sl") == 0


def test_cpoe_still_raises_a_plain_interaction(
    client, analyst_headers, seed_substances_and_drugs
):
    """CPOE pairs drugs by overlapping periods instead of a shared expire date."""
    _add_relation(_SUBSTANCE_A[0], _SUBSTANCE_B[0], "it", "high")

    payload = _prescription_with(
        client,
        analyst_headers,
        [
            {"idDrug": _DRUG_A[0], "idSegment": _SEGMENT_CPOE},
            {"idDrug": _DRUG_B[0], "idSegment": _SEGMENT_CPOE},
        ],
        cpoe=True,
    )

    assert _count(payload, "it") == 1
