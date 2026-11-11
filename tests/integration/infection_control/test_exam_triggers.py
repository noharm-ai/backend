"""Tests: infection control exam triggers (exam_trigger_service)

The users define the exam trigger rules (GET/PUT
/infection-control/exam-triggers, kept in the schema's memoria) on the exams
of the catalog (the active public.exame flagged gatilho_controle_infeccao),
matched by their reference (segmentoexame.tpexame_ref);
CKD21 is calculated from the creatinine. A review turns rules on per drug
evaluation, keeping each with its baseline (from the exame table); the job
opens an EXAM_RESULT reason when a later result in the exams cache (Redis,
faked here as the cache job of backend-private fills it) meets a rule, and a
new evaluation settles it without reopening it on the same result.
"""

import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from models.enums import InfectionControlPendingTypeEnum, MemoryEnum
from services import cache_service
from tests.conftest import session, session_commit
from tests.integration.infection_control.helpers import (
    ADULT_SEGMENT,
    ANTIMICROBIAL_DRUG,
    EXPIRED,
    PATIENT_ID,
    PENDING,
    REVISED,
    _evaluations,
    _open_pendings,
    _pendings,
    _prescribe_today,
    _record,
    _review,
    _run_job,
)
from utils import status

EXAM_RESULT = InfectionControlPendingTypeEnum.EXAM_RESULT.value
RULES_KIND = MemoryEnum.INFECTION_CONTROL_EXAM_TRIGGERS.value
URL = "/infection-control/exam-triggers"
# the schema's own codes: PCR and temperature mapped to the references, the
# creatinine found by its abbreviation (the CKDs are calculated from it)
PCR_TYPE = "PCR_CI_TEST"
TEMPERATURE_TYPE = "TAX_CI_TEST"
CREATININE_TYPE = "CR_CI_TEST"

# the catalog: public.exame rows (tpexame, nome, ativo, gatilho_controle_infeccao)
CATALOG = (
    ("pcru", "PCR", True, True),
    ("temp", "Temperatura", True, True),
    ("ckd", "CKD", True, True),
    ("ckd21", "CKD21", True, True),
    ("h_conleuc", "Leucócitos Absoluto", True, True),
    # left out of the catalog: inactive, or not flagged for the triggers
    ("van", "Vancocinemia", False, True),
    ("k", "Potássio", True, False),
)
CATALOG_REFS = ["ckd", "ckd21", "h_conleuc", "pcru", "temp"]  # by name

PCR_RISE = {
    "name": "PCR em elevação",
    "examRef": "pcru",
    "valueAbove": 50,
    "variationAtLeast": 20,
    "enabledByDefault": True,
}
FEVER_AFTER_D3 = {
    "name": "Febre após D3",
    "examRef": "temp",
    "valueAbove": 38,
    "fromCourseDay": 4,
}
EGFR_FALL = {
    "name": "TFG caiu",
    "examRef": "ckd21",
    "valueBelow": 60,
    "variationBelow": -25,
}


def _delete_catalog():
    """Removes the catalog's exams from public.exame"""
    session.execute(
        text("DELETE FROM public.exame WHERE tpexame = ANY(:types)"),
        {"types": [row[0] for row in CATALOG]},
    )
    session_commit()


@pytest.fixture(autouse=True)
def catalog():
    """The global exams (public.exame) the rules can watch, and two they
    can't; removed afterwards"""
    _delete_catalog()
    for exam_type, name, active, trigger in CATALOG:
        session.execute(
            text(
                "INSERT INTO public.exame (tpexame, nome, abrev, unidade, ativo, "
                "gatilho_controle_infeccao, created_at, created_by) "
                "VALUES (:exam_type, :name, :name, '-', :active, :trigger, now(), 0)"
            ),
            {
                "exam_type": exam_type,
                "name": name,
                "active": active,
                "trigger": trigger,
            },
        )
    session_commit()
    yield
    _delete_catalog()


def _delete_rules():
    """Removes the schema's rules"""
    session.execute(
        text("DELETE FROM demo.memoria WHERE tipo = :kind"), {"kind": RULES_KIND}
    )
    session_commit()


@pytest.fixture
def no_rules():
    """The schema without rules, before and after"""
    _delete_rules()
    yield
    _delete_rules()


def _delete_global_rules():
    """Removes the global rules (public.memoria)"""
    session.execute(
        text("DELETE FROM public.memoria WHERE tipo = :kind"), {"kind": RULES_KIND}
    )
    session_commit()


@pytest.fixture
def global_rules(no_rules):
    """Global rules in public.memoria (one with an id, one without, one
    invalid: no condition), the schema without its own; removed afterwards"""
    _delete_global_rules()
    session.execute(
        text(
            "INSERT INTO public.memoria (tipo, valor, update_at, update_by) "
            "VALUES (:kind, :value, now(), 0)"
        ),
        {
            "kind": RULES_KIND,
            "value": json.dumps(
                [
                    {**PCR_RISE, "id": "global-pcr"},
                    FEVER_AFTER_D3,
                    {**FEVER_AFTER_D3, "name": "Sem condição", "valueAbove": None},
                ]
            ),
        },
    )
    session_commit()
    yield
    _delete_global_rules()


def _schema_rules_records():
    """The schema's memoria records keeping the rules"""
    return session.execute(
        text("SELECT valor FROM demo.memoria WHERE tipo = :kind"),
        {"kind": RULES_KIND},
    ).all()


def _save(client, headers, rules):
    """Saves the schema's rules"""
    return client.put(URL, json={"rules": rules}, headers=headers)


@pytest.fixture
def rules(client, infection_controller_headers, infection_control, no_rules):
    """The schema's rules saved by the users: their ids by name"""
    response = _save(
        client, infection_controller_headers, [PCR_RISE, FEVER_AFTER_D3, EGFR_FALL]
    )
    assert response.status_code == status.HTTP_200_OK, response.get_json()
    return {r["name"]: r["id"] for r in response.get_json()["data"]["rules"]}


@pytest.fixture
def mapped_exams():
    """The schema's PCR, temperature and creatinine exams; removes them and
    the patient's results afterwards"""
    for exam_type, exam_ref, initials in (
        (PCR_TYPE, "pcru", PCR_TYPE),
        (TEMPERATURE_TYPE, "temp", TEMPERATURE_TYPE),
        (CREATININE_TYPE, None, "Creatinina"),
    ):
        session.execute(
            text(
                "INSERT INTO demo.segmentoexame "
                "(idsegmento, tpexame, tpexame_ref, abrev, nome, ativo, update_by) "
                "VALUES (:segment, :exam_type, :exam_ref, :initials, :exam_type, "
                "true, 0)"
            ),
            {
                "segment": ADULT_SEGMENT,
                "exam_type": exam_type,
                "exam_ref": exam_ref,
                "initials": initials,
            },
        )
    session_commit()

    yield

    params = {
        "types": [PCR_TYPE, TEMPERATURE_TYPE, CREATININE_TYPE],
        "patient": PATIENT_ID,
    }
    session.execute(
        text(
            "DELETE FROM demo.exame WHERE fkpessoa = :patient AND tpexame = ANY(:types)"
        ),
        params,
    )
    session.execute(
        text("DELETE FROM demo.segmentoexame WHERE tpexame = ANY(:types)"), params
    )
    session_commit()


# the exams cache: key -> {tpexame as the schema writes it: the result as json}
_cache: dict[str, dict[str, str]] = {}


@pytest.fixture(autouse=True)
def exams_cache(monkeypatch):
    """The exams cache, empty at the start of each test (tests never call
    Redis)"""
    _cache.clear()
    monkeypatch.setattr(
        cache_service,
        "get_hgetall",
        lambda key: {k: json.loads(v) for k, v in _cache.get(key, {}).items()},
    )
    yield
    _cache.clear()


def _cache_exam(exam_type, value, date):
    """Caches a result as the exams cache job does: it replaces the cached
    one only when newer"""
    exams = _cache.setdefault(f"demo:{PATIENT_ID}:exames", {})
    current = exams.get(exam_type)
    if current and datetime.fromisoformat(json.loads(current)["date"]) >= date:
        return
    exams[exam_type] = json.dumps(
        {"value": value, "prev": None, "unit": None, "date": date.isoformat()}
    )


_exam_ids = iter(range(990_000_000, 999_999_999))


def _exam(exam_type, value, date, cached=True):
    """A result of the test patient, cached unless told otherwise"""
    session.execute(
        text(
            "INSERT INTO demo.exame (fkexame, fkpessoa, dtexame, tpexame, resultado) "
            "VALUES (:id, :patient, :date, :exam_type, :value)"
        ),
        {
            "id": next(_exam_ids),
            "patient": PATIENT_ID,
            "date": date,
            "exam_type": exam_type,
            "value": value,
        },
    )
    session_commit()
    if cached:
        _cache_exam(exam_type, value, date)


def _reviewed(client, headers, admission_number, exam_triggers, triggers=()):
    """Reviews the antimicrobial turning these rules on"""
    response = _review(
        client,
        headers,
        admission_number,
        evaluations=[ANTIMICROBIAL_DRUG],
        exam_triggers=exam_triggers,
        triggers=list(triggers),
    )
    assert response.status_code == status.HTTP_200_OK, response.get_json()
    return response.get_json()["data"]


def _listed(client, headers):
    """The rules and the exam catalog, as the screens get them"""
    response = client.get(URL, headers=headers)
    assert response.status_code == status.HTTP_200_OK, response.get_json()
    return response.get_json()["data"]


# --- the rules ---


def test_no_rules_until_the_users_define_them(
    client, infection_controller_headers, infection_control, no_rules
):
    """No rules; the catalog lists the exams a rule can watch: the active
    public.exame flagged for the triggers, by name"""
    data = _listed(client, infection_controller_headers)

    assert data["rules"] == []
    assert [e["examRef"] for e in data["exams"]] == CATALOG_REFS
    assert {e["examRef"]: e["name"] for e in data["exams"]}["pcru"] == "PCR"


def test_a_schema_without_rules_gets_a_copy_of_the_global_ones(
    client, infection_controller_headers, infection_control, global_rules
):
    """The first read copies the valid global rules into the schema (keeping
    an id, giving one to a rule without it), once"""
    data = _listed(client, infection_controller_headers)

    assert [r["name"] for r in data["rules"]] == ["PCR em elevação", "Febre após D3"]
    pcr, fever = data["rules"]
    assert pcr["id"] == "global-pcr"
    assert fever["id"]

    (record,) = _schema_rules_records()
    assert [r["id"] for r in record.valor] == ["global-pcr", fever["id"]]

    # read again: the schema's own, not a new copy
    assert _listed(client, infection_controller_headers)["rules"] == data["rules"]
    assert len(_schema_rules_records()) == 1


def test_the_copy_is_the_schemas_own(
    client, infection_controller_headers, infection_control, global_rules
):
    """The users edit the copied rules by their ids; removing them all keeps
    the schema without rules (no new copy)"""
    _listed(client, infection_controller_headers)

    response = _save(
        client,
        infection_controller_headers,
        [{**PCR_RISE, "id": "global-pcr", "valueAbove": 80}],
    )
    assert response.status_code == status.HTTP_200_OK, response.get_json()
    (pcr,) = _listed(client, infection_controller_headers)["rules"]
    assert pcr["valueAbove"] == 80

    assert _save(client, infection_controller_headers, []).status_code == 200
    assert _listed(client, infection_controller_headers)["rules"] == []


def test_saving_before_reading_edits_the_copy(
    client, infection_controller_headers, infection_control, global_rules
):
    """A save that comes first copies the global rules too, so their ids are
    the schema's"""
    response = _save(
        client,
        infection_controller_headers,
        [{**PCR_RISE, "id": "global-pcr", "valueAbove": 70}],
    )

    assert response.status_code == status.HTTP_200_OK, response.get_json()
    (pcr,) = _listed(client, infection_controller_headers)["rules"]
    assert pcr["id"] == "global-pcr"
    assert pcr["valueAbove"] == 70


def test_saves_the_rules(client, infection_controller_headers, rules):
    """Each new rule gets an id; the list keeps the order and the fields"""
    data = _listed(client, infection_controller_headers)

    assert [r["name"] for r in data["rules"]] == [
        "PCR em elevação",
        "Febre após D3",
        "TFG caiu",
    ]
    pcr = data["rules"][0]
    assert pcr["id"] == rules["PCR em elevação"]
    assert pcr["valueAbove"] == 50
    assert pcr["variationAtLeast"] == 20
    assert pcr["enabledByDefault"] is True
    assert data["rules"][1]["enabledByDefault"] is False


def test_editing_keeps_the_id_and_a_rule_left_out_is_deleted(
    client, infection_controller_headers, rules
):
    """The list replaces the kept one: a rule sent with its id is edited, one
    left out is deleted"""
    response = _save(
        client,
        infection_controller_headers,
        [{**FEVER_AFTER_D3, "id": rules["Febre após D3"], "valueAbove": 38.5}],
    )

    assert response.status_code == status.HTTP_200_OK
    (fever,) = _listed(client, infection_controller_headers)["rules"]
    assert fever["id"] == rules["Febre após D3"]
    assert fever["valueAbove"] == 38.5


@pytest.mark.parametrize(
    "rule",
    [
        {**FEVER_AFTER_D3, "examRef": "creatinina"},
        {**FEVER_AFTER_D3, "examRef": "van"},
        {**FEVER_AFTER_D3, "examRef": "k"},
        {**FEVER_AFTER_D3, "valueAbove": None},
        {**FEVER_AFTER_D3, "name": ""},
        {**FEVER_AFTER_D3, "id": "unknown"},
    ],
)
def test_refuses_an_invalid_rule(client, infection_controller_headers, rules, rule):
    """An exam out of the catalog (unknown, inactive or not flagged), no
    condition, no name or an id that isn't a rule: nothing changes"""
    response = _save(client, infection_controller_headers, [rule])

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert len(_listed(client, infection_controller_headers)["rules"]) == 3


def _unflag(exam_type):
    """Takes an exam out of the catalog"""
    session.execute(
        text(
            "UPDATE public.exame SET gatilho_controle_infeccao = false "
            "WHERE tpexame = :t"
        ),
        {"t": exam_type},
    )
    session_commit()


def test_a_rule_on_an_exam_taken_out_of_the_catalog_stays_unavailable(
    client, infection_controller_headers, rules
):
    """A kept rule whose exam is no longer flagged stays, unavailable, and
    can be saved again as it is; it can't be moved to an exam out of the
    catalog, and a new rule on it is refused"""
    _unflag("temp")

    data = _listed(client, infection_controller_headers)
    fever = next(r for r in data["rules"] if r["name"] == "Febre após D3")
    assert fever["available"] is False
    assert "temp" not in [e["examRef"] for e in data["exams"]]

    kept = [{k: v for k, v in r.items() if k != "available"} for r in data["rules"]]
    response = _save(client, infection_controller_headers, kept)
    assert response.status_code == status.HTTP_200_OK, response.get_json()
    assert len(_listed(client, infection_controller_headers)["rules"]) == 3

    moved = [{**r, "examRef": "k"} if r["id"] == fever["id"] else r for r in kept]
    assert _save(client, infection_controller_headers, moved).status_code == 400

    assert (
        _save(client, infection_controller_headers, [FEVER_AFTER_D3]).status_code == 400
    )
    assert len(_listed(client, infection_controller_headers)["rules"]) == 3


def test_saving_needs_the_infection_control_permission(
    client, analyst_headers, infection_control, no_rules
):
    """Only infection control writes the rules"""
    response = _save(client, analyst_headers, [FEVER_AFTER_D3])

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_the_generic_memory_endpoint_cant_write_them(
    client, infection_controller_headers, infection_control, no_rules
):
    """The rules are written only by their own endpoint, which validates them"""
    response = client.put(
        f"/memory/unique/{RULES_KIND}",
        json={"value": [{"id": "x", "name": "x", "examRef": "x"}]},
        headers=infection_controller_headers,
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert _listed(client, infection_controller_headers)["rules"] == []


def test_available_when_the_schema_has_the_exam(
    client, infection_controller_headers, rules, mapped_exams
):
    """A rule (and an exam of the catalog) is available when an active exam
    of the schema is mapped to its reference, or, for a CKD, the schema has a
    creatinine: otherwise it would never fire"""
    session.execute(
        text("UPDATE demo.segmentoexame SET ativo = false WHERE tpexame = :t"),
        {"t": TEMPERATURE_TYPE},
    )
    session_commit()

    data = _listed(client, infection_controller_headers)

    assert {r["name"]: r["available"] for r in data["rules"]} == {
        "PCR em elevação": True,
        "Febre após D3": False,
        "TFG caiu": True,
    }
    assert {e["examRef"] for e in data["exams"] if e["available"]} == {
        "pcru",
        "ckd",
        "ckd21",
    }


def test_the_current_results_of_the_admission(
    client, infection_controller_headers, infection_control, mapped_exams, admission
):
    """With an admission, the latest result of each exam the schema has, as a
    review saved now would keep it (a CKD calculated from the creatinine);
    none for an exam without results, and nothing without an admission"""
    _exam(PCR_TYPE, 30, datetime.now() - timedelta(days=2))
    _exam(PCR_TYPE, 40, datetime.now() - timedelta(hours=5))
    _exam(CREATININE_TYPE, 0.8, datetime.now() - timedelta(hours=3))

    response = client.get(
        f"{URL}?admissionNumber={admission}", headers=infection_controller_headers
    )
    assert response.status_code == status.HTTP_200_OK, response.get_json()
    current = response.get_json()["data"]["current"]

    assert set(current) == {"pcru", "temp", "ckd", "ckd21"}
    assert current["pcru"]["value"] == 40
    assert current["pcru"]["examType"] == PCR_TYPE.lower()
    assert current["temp"] is None
    assert current["ckd21"]["rawValue"] == 0.8
    assert current["ckd21"]["value"] > 60
    assert "current" not in _listed(client, infection_controller_headers)


def test_refuses_an_admission_number_that_isnt_one(
    client, infection_controller_headers, infection_control
):
    """The admission number is read as a number"""
    response = client.get(
        f"{URL}?admissionNumber=abc", headers=infection_controller_headers
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST


# --- the review and the rule ---


def test_review_keeps_the_rule_and_its_baseline(
    client, infection_controller_headers, rules, mapped_exams, admission
):
    """Each rule is copied on the evaluation, among its triggers after the
    pending types, with the latest result of its exam; none when there is
    none"""
    _prescribe_today(admission)
    _exam(PCR_TYPE, 30, datetime.now() - timedelta(days=2))
    _exam(PCR_TYPE, 40, datetime.now() - timedelta(hours=5))

    data = _reviewed(
        client,
        infection_controller_headers,
        admission,
        [rules["PCR em elevação"], rules["Febre após D3"]],
        triggers=[EXPIRED],
    )

    (evaluation,) = _evaluations(admission)
    expired, pcr, fever = evaluation["gatilhos"]
    assert expired == EXPIRED
    assert pcr["type"] == "exam"
    assert pcr["id"] == rules["PCR em elevação"]
    assert pcr["examRef"] == "pcru"
    assert pcr["variationAtLeast"] == 20
    assert "enabledByDefault" not in pcr
    assert pcr["baseline"]["value"] == 40
    assert pcr["baseline"]["examType"] == PCR_TYPE.lower()
    assert fever["baseline"] is None
    assert data["courses"][0]["evaluation"]["triggers"] == [EXPIRED]
    assert data["courses"][0]["evaluation"]["examTriggers"] == [pcr, fever]


def test_a_later_result_sends_the_patient_back_to_pending(
    client, infection_controller_headers, rules, mapped_exams, admission
):
    """A result after the review meeting the rule opens a reason of the drug;
    a new evaluation settles it and the same result doesn't reopen it"""
    _prescribe_today(admission)
    _exam(PCR_TYPE, 50, datetime.now() - timedelta(hours=5))
    _reviewed(
        client, infection_controller_headers, admission, [rules["PCR em elevação"]]
    )

    # over 50 but only 10% over the baseline
    _exam(PCR_TYPE, 55, datetime.now() - timedelta(hours=2))
    _run_job(admission)
    assert _record(admission)["tp_status"] == REVISED

    # exactly 20% over 50
    _exam(PCR_TYPE, 60, datetime.now() - timedelta(hours=1))
    _run_job(admission)

    assert _record(admission)["tp_status"] == PENDING
    (pending,) = _open_pendings(admission)
    assert pending["tp_pendencia"] == EXAM_RESULT
    assert pending["fkmedicamento"] == ANTIMICROBIAL_DRUG
    assert (
        pending["fkci_avaliacao_atm"]
        == _evaluations(admission)[0]["idci_avaliacao_atm"]
    )
    (match,) = pending["detalhes"]["matches"]
    assert match["id"] == rules["PCR em elevação"]
    assert match["result"]["value"] == 60
    assert match["baseline"]["value"] == 50
    assert match["variation"] == 20

    # the job running again keeps one reason
    _run_job(admission)
    assert len(_open_pendings(admission)) == 1

    data = _reviewed(
        client, infection_controller_headers, admission, [rules["PCR em elevação"]]
    )
    assert data["status"] == REVISED
    assert _evaluations(admission)[1]["gatilhos"][0]["baseline"]["value"] == 60

    _run_job(admission)
    assert _record(admission)["tp_status"] == REVISED
    assert _open_pendings(admission) == []
    assert [p["tp_pendencia"] for p in _pendings(admission)].count(EXAM_RESULT) == 1


def test_ckd21_calculated_from_the_creatinine(
    client, infection_controller_headers, rules, mapped_exams, admission
):
    """The CKD21 of the patient (an adult) is calculated from each creatinine:
    a fall of more than 25% to below 60 fires"""
    _prescribe_today(admission)
    _exam(CREATININE_TYPE, 0.8, datetime.now() - timedelta(hours=5))
    _reviewed(client, infection_controller_headers, admission, [rules["TFG caiu"]])

    (evaluation,) = _evaluations(admission)
    baseline = evaluation["gatilhos"][0]["baseline"]
    assert baseline["rawValue"] == 0.8
    assert baseline["value"] > 60

    _exam(CREATININE_TYPE, 1.6, datetime.now() - timedelta(hours=1))
    _run_job(admission)

    assert _record(admission)["tp_status"] == PENDING
    (pending,) = _open_pendings(admission)
    (match,) = pending["detalhes"]["matches"]
    assert match["result"]["rawValue"] == 1.6
    assert match["result"]["value"] < 60
    assert match["variation"] < -25


def test_a_rule_deleted_meanwhile_is_left_out(
    client, infection_controller_headers, rules, mapped_exams, admission
):
    """A form loaded before a rule was deleted still saves, without it"""
    _prescribe_today(admission)
    _save(client, infection_controller_headers, [])

    _reviewed(client, infection_controller_headers, admission, [rules["Febre após D3"]])

    (evaluation,) = _evaluations(admission)
    assert evaluation["gatilhos"] == []


def test_rules_not_turned_on_are_ignored(
    client, infection_controller_headers, rules, mapped_exams, admission
):
    """A result meeting a rule the evaluation didn't turn on changes nothing"""
    _prescribe_today(admission)
    _exam(PCR_TYPE, 10, datetime.now() - timedelta(hours=5))
    _reviewed(client, infection_controller_headers, admission, [])

    _exam(PCR_TYPE, 300, datetime.now() - timedelta(hours=1))
    _exam(TEMPERATURE_TYPE, 39.5, datetime.now() - timedelta(hours=1))
    _run_job(admission)

    assert _record(admission)["tp_status"] == REVISED
    assert _open_pendings(admission) == []


def test_the_rule_reads_the_exams_cache(
    client, infection_controller_headers, rules, mapped_exams, admission
):
    """A result in the exame table that the cache doesn't have yet changes
    nothing; once cached (the cache job then queues the admission) it fires"""
    _prescribe_today(admission)
    _exam(PCR_TYPE, 50, datetime.now() - timedelta(hours=5))
    _reviewed(
        client, infection_controller_headers, admission, [rules["PCR em elevação"]]
    )

    date = datetime.now() - timedelta(hours=1)
    _exam(PCR_TYPE, 80, date, cached=False)
    _run_job(admission)
    assert _record(admission)["tp_status"] == REVISED

    _cache_exam(PCR_TYPE, 80, date)
    _run_job(admission)
    assert _record(admission)["tp_status"] == PENDING
    (pending,) = _open_pendings(admission)
    assert pending["detalhes"]["matches"][0]["result"]["value"] == 80
