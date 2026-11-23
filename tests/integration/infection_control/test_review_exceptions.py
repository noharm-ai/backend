"""Tests: antimicrobials exempt from the infection control review

Each schema keeps a list of antimicrobials whose courses need no review
(GET/PUT /infection-control/review-exceptions, in its memoria, written only by
WRITE_INFECTION_CONTROL): a substance covers every drug of it, a drug (any
antimicrobial, with a substance or not) covers only itself. An exempt course opens no reason,
its open ones are settled (NOT_REQUIRED), the record running only exempt
courses is revised and hidden from the worklist unless asked, and the report
summary marks the course reviewRequired false (it still counts in DOT/LOT).
"""

import pytest
from sqlalchemy import text

from models.enums import (
    AdmissionQueueReasonEnum,
    InfectionControlResolutionEnum,
    MemoryEnum,
)
from tests.conftest import session, session_commit
from tests.integration.infection_control.helpers import (
    ANTIMICROBIAL_DRUG,
    NEVER_REVIEWED,
    NO_EVALUATION,
    OTHER_DRUG,
    PENDING,
    REVISED,
    _open_pendings,
    _pendings,
    _prescalc,
    _prescribe,
    _prescribe_today,
    _day,
    _queued,
    _record,
    _review,
    _run_job,
)
from utils import status

URL = "/infection-control/review-exceptions"
KIND = MemoryEnum.INFECTION_CONTROL_REVIEW_EXCEPTIONS.value
PREVIOUS_KIND = MemoryEnum.INFECTION_CONTROL_REVIEW_EXCEPTIONS_PREVIOUS.value
NOHARM_USER_EMAIL = "test-review-exceptions-noharm@example.com"
SUBSTANCE = 9070101
NOT_REQUIRED = InfectionControlResolutionEnum.NOT_REQUIRED.value


def _delete_exceptions():
    """Delete the list and the version it replaced"""
    session.execute(
        text("DELETE FROM demo.memoria WHERE tipo IN (:kind, :previous)"),
        {"kind": KIND, "previous": PREVIOUS_KIND},
    )
    session_commit()


@pytest.fixture(autouse=True)
def no_exceptions():
    """No review exceptions before and after each test"""
    _delete_exceptions()
    yield
    _delete_exceptions()


@pytest.fixture
def antimicrobial_substance():
    """Give the antimicrobial drug a substance"""
    session.execute(
        text(
            "INSERT INTO public.substancia (sctid, nome, ativo) "
            "VALUES (:sctid, 'ZZTEST SUBSTANCIA ISENTA', true)"
        ),
        {"sctid": SUBSTANCE},
    )
    session.execute(
        text("UPDATE demo.medicamento SET sctid = :sctid WHERE fkmedicamento = :id"),
        {"sctid": SUBSTANCE, "id": ANTIMICROBIAL_DRUG},
    )
    session_commit()

    yield SUBSTANCE

    session.execute(
        text("UPDATE demo.medicamento SET sctid = NULL WHERE fkmedicamento = :id"),
        {"id": ANTIMICROBIAL_DRUG},
    )
    session.execute(
        text("DELETE FROM public.substancia WHERE sctid = :sctid"),
        {"sctid": SUBSTANCE},
    )
    session_commit()


def _save(client, headers, substances=(), drugs=()):
    """PUT the review exceptions"""
    return client.put(
        URL,
        json={"substances": list(substances), "drugs": list(drugs)},
        headers=headers,
    )


def _saved(client, headers, **kwargs):
    """PUT the review exceptions, expecting success"""
    response = _save(client, headers, **kwargs)
    assert response.status_code == status.HTTP_200_OK, response.get_json()
    return response.get_json()["data"]


def _worklist(client, headers, **filters):
    """Admission numbers of the open worklist (no admission number asked)"""
    response = client.post(
        "/infection-control/admissions",
        json={"status": [PENDING, REVISED], "limit": 500, **filters},
        headers=headers,
    )
    assert response.status_code == status.HTTP_200_OK, response.get_json()
    return {a["admissionNumber"] for a in response.get_json()["data"]["admissions"]}


def _summary_courses(admission_number):
    """The courses of the record's report summary"""
    row = session.execute(
        text(
            "SELECT resumo_acompanhamento FROM demo.ci_atendimento "
            "WHERE nratendimento = :admission"
        ),
        {"admission": admission_number},
    ).first()
    return row[0]["courses"]


# --- the list ---


def test_empty_without_a_record(
    client, infection_controller_headers, infection_control
):
    """No record reviews every antimicrobial"""
    response = client.get(URL, headers=infection_controller_headers)

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"] == {
        "substances": [],
        "drugs": [],
        "updatedAt": None,
        "updatedBy": None,
        "previous": None,
    }


def test_saves_substances_and_drugs_with_their_names(
    client,
    infection_controller_headers,
    infection_control,
    antimicrobial_substance,
    second_antimicrobial,
):
    """The list keeps substances and drugs, shown with their names"""
    _saved(
        client,
        infection_controller_headers,
        substances=[antimicrobial_substance],
        drugs=[second_antimicrobial],
    )

    data = client.get(URL, headers=infection_controller_headers).get_json()["data"]
    assert data["substances"] == [
        {"id": str(antimicrobial_substance), "name": "ZZTEST SUBSTANCIA ISENTA"}
    ]
    assert data["drugs"] == [{"id": str(OTHER_DRUG), "name": "BISACODIL 5 mg CP"}]
    assert data["updatedAt"] is not None


def test_options_offer_substances_and_drugs_of_antimicrobials(
    client,
    infection_controller_headers,
    infection_control,
    antimicrobial_substance,
    second_antimicrobial,
):
    """The search offers the substances of antimicrobial drugs and every
    antimicrobial drug, with a substance or not; no drug that isn't one"""
    data = client.get(
        f"{URL}/options?q=ZZTEST", headers=infection_controller_headers
    ).get_json()["data"]
    assert data["substances"] == [
        {"id": str(antimicrobial_substance), "name": "ZZTEST SUBSTANCIA ISENTA"}
    ]

    drugs = client.get(
        f"{URL}/options?q=BISACODIL", headers=infection_controller_headers
    ).get_json()["data"]["drugs"]
    assert {"id": str(OTHER_DRUG), "name": "BISACODIL 5 mg CP"} in drugs

    ampicilin = client.get(
        f"{URL}/options?q=AMPICILINA", headers=infection_controller_headers
    ).get_json()["data"]["drugs"]
    # the antimicrobial with a substance is offered by itself too
    assert str(ANTIMICROBIAL_DRUG) in {d["id"] for d in ampicilin}


def test_options_leave_out_drugs_that_are_not_antimicrobials(
    client, infection_controller_headers, infection_control
):
    """Drug 4 (BISACODIL) is not an antimicrobial in the seed data"""
    drugs = client.get(
        f"{URL}/options?q=BISACODIL", headers=infection_controller_headers
    ).get_json()["data"]["drugs"]
    assert drugs == []


def test_rejects_what_is_not_an_antimicrobial(
    client, infection_controller_headers, infection_control
):
    """Drug 4 is not an antimicrobial in the seed data"""
    response = _save(client, infection_controller_headers, drugs=[OTHER_DRUG])

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert (
        client.get(URL, headers=infection_controller_headers).get_json()["data"][
            "drugs"
        ]
        == []
    )


def test_rejects_a_substance_of_no_antimicrobial(
    client, infection_controller_headers, infection_control
):
    """A substance no antimicrobial drug of the schema has can't be listed"""
    response = _save(client, infection_controller_headers, substances=[9070199])

    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.parametrize(
    "headers_fixture", ["analyst_headers", "config_manager_headers"]
)
def test_only_infection_control_writes_it(
    request, client, infection_control, headers_fixture
):
    """Viewing roles read the list but can't change it"""
    headers = request.getfixturevalue(headers_fixture)

    assert client.get(URL, headers=headers).status_code == status.HTTP_200_OK
    response = _save(client, headers, drugs=[ANTIMICROBIAL_DRUG])
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_the_generic_memory_endpoints_cant_write_it(
    client, infection_controller_headers, analyst_headers, infection_control
):
    """Written only by its own endpoint: neither by kind nor by relabeling the
    record through its id"""
    response = client.put(
        f"/memory/unique/{KIND}",
        json={"value": {"drugs": [ANTIMICROBIAL_DRUG]}},
        headers=infection_controller_headers,
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED

    _saved(client, infection_controller_headers, drugs=[ANTIMICROBIAL_DRUG])
    id_record = session.execute(
        text("SELECT idmemoria FROM demo.memoria WHERE tipo = :kind"), {"kind": KIND}
    ).scalar()
    response = client.put(
        f"/memory/{id_record}",
        json={"type": "any-kind", "value": {}},
        headers=analyst_headers,
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    data = client.get(URL, headers=infection_controller_headers).get_json()["data"]
    assert [d["id"] for d in data["drugs"]] == [str(ANTIMICROBIAL_DRUG)]


# --- the previous version ---


def _demo_user_name():
    """The name of the user the tests log in as"""
    return session.execute(
        text("SELECT nome FROM public.usuario WHERE email = 'demo'")
    ).scalar()


@pytest.fixture
def noharm_user():
    """A user of the NoHarm schema"""
    session.execute(
        text("DELETE FROM public.usuario WHERE email = :email"),
        {"email": NOHARM_USER_EMAIL},
    )
    id_user = session.execute(
        text(
            "INSERT INTO public.usuario (nome, email, senha, schema, config, ativo) "
            "VALUES ('Ciclano de Tal', :email, 'x', 'hsc_test', "
            "CAST('{}' AS json), true) RETURNING idusuario"
        ),
        {"email": NOHARM_USER_EMAIL},
    ).scalar()
    session_commit()

    yield id_user

    session.execute(
        text("DELETE FROM public.usuario WHERE email = :email"),
        {"email": NOHARM_USER_EMAIL},
    )
    session_commit()


def test_first_save_has_no_previous_version(
    client, infection_controller_headers, infection_control
):
    """The first list replaces nothing; it shows who saved it"""
    data = _saved(client, infection_controller_headers, drugs=[ANTIMICROBIAL_DRUG])

    assert data["updatedBy"] == _demo_user_name()
    assert data["previous"] is None


def test_a_change_keeps_the_version_it_replaced(
    client,
    infection_controller_headers,
    infection_control,
    antimicrobial_substance,
    second_antimicrobial,
):
    """The version replaced is kept, with its names, when and by whom"""
    first = _saved(
        client,
        infection_controller_headers,
        substances=[antimicrobial_substance],
        drugs=[second_antimicrobial],
    )
    _saved(client, infection_controller_headers, drugs=[second_antimicrobial])

    data = client.get(URL, headers=infection_controller_headers).get_json()["data"]
    assert data["substances"] == []
    assert data["drugs"] == [{"id": str(OTHER_DRUG), "name": "BISACODIL 5 mg CP"}]
    assert data["previous"] == {
        "substances": [
            {"id": str(antimicrobial_substance), "name": "ZZTEST SUBSTANCIA ISENTA"}
        ],
        "drugs": [{"id": str(OTHER_DRUG), "name": "BISACODIL 5 mg CP"}],
        "updatedAt": first["updatedAt"],
        "updatedBy": _demo_user_name(),
    }

    # only the last version replaced is kept
    _saved(client, infection_controller_headers)
    data = client.get(URL, headers=infection_controller_headers).get_json()["data"]
    assert data["drugs"] == []
    assert data["previous"]["substances"] == []
    assert [d["id"] for d in data["previous"]["drugs"]] == [str(OTHER_DRUG)]
    assert (
        session.execute(
            text("SELECT count(*) FROM demo.memoria WHERE tipo = :kind"),
            {"kind": PREVIOUS_KIND},
        ).scalar()
        == 1
    )


def test_saving_no_change_keeps_the_previous_version(
    client, infection_controller_headers, infection_control
):
    """A save that changes nothing writes nothing"""
    _saved(client, infection_controller_headers, drugs=[ANTIMICROBIAL_DRUG])
    second = _saved(client, infection_controller_headers)

    again = _saved(client, infection_controller_headers)

    assert again["updatedAt"] == second["updatedAt"]
    assert [d["id"] for d in again["previous"]["drugs"]] == [str(ANTIMICROBIAL_DRUG)]


def test_a_change_by_noharm_shows_noharm(
    client, infection_controller_headers, infection_control, noharm_user
):
    """A version saved by a user of the NoHarm schema shows NoHarm, not the
    person, in the list and in the version it replaced"""
    _saved(client, infection_controller_headers, drugs=[ANTIMICROBIAL_DRUG])
    session.execute(
        text("UPDATE demo.memoria SET update_by = :id WHERE tipo = :kind"),
        {"id": noharm_user, "kind": KIND},
    )
    session_commit()

    data = client.get(URL, headers=infection_controller_headers).get_json()["data"]
    assert data["updatedBy"] == "NoHarm"

    data = _saved(client, infection_controller_headers)
    assert data["updatedBy"] == _demo_user_name()
    assert data["previous"]["updatedBy"] == "NoHarm"


def test_the_generic_memory_endpoints_cant_write_the_previous_version(
    client, infection_controller_headers, infection_control
):
    """The version kept is written only by the save"""
    response = client.put(
        f"/memory/unique/{PREVIOUS_KIND}",
        json={"value": {"drugs": [ANTIMICROBIAL_DRUG]}},
        headers=infection_controller_headers,
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


# --- the rule ---


def test_exempt_drug_opens_no_reason(
    client, infection_controller_headers, infection_control, admission
):
    """A record running only an exempt drug is followed, revised and without
    reasons; its course still feeds the report summary, marked not to review"""
    _saved(client, infection_controller_headers, drugs=[ANTIMICROBIAL_DRUG])

    _prescribe_today(admission)

    record = _record(admission)
    assert record["tp_status"] == REVISED
    assert record["indicadores"]["reviewRequired"] is False
    assert record["indicadores"]["courses"][0]["reviewRequired"] is False
    assert _open_pendings(admission) == []
    (course,) = _summary_courses(admission)
    assert course["reviewRequired"] is False


def test_exempt_by_substance(
    client,
    infection_controller_headers,
    infection_control,
    admission,
    antimicrobial_substance,
):
    """A substance covers its drugs"""
    _saved(client, infection_controller_headers, substances=[antimicrobial_substance])

    _prescribe_today(admission)

    assert _record(admission)["tp_status"] == REVISED
    assert _open_pendings(admission) == []


def test_exempt_by_drug_with_a_substance(
    client,
    infection_controller_headers,
    infection_control,
    admission,
    antimicrobial_substance,
):
    """A drug with a substance may be listed by itself: it is exempt, its
    substance stays reviewed for the other drugs of it"""
    _saved(client, infection_controller_headers, drugs=[ANTIMICROBIAL_DRUG])

    _prescribe_today(admission)

    assert _record(admission)["tp_status"] == REVISED
    assert _open_pendings(admission) == []
    data = client.get(URL, headers=infection_controller_headers).get_json()["data"]
    assert data["substances"] == []
    assert [d["id"] for d in data["drugs"]] == [str(ANTIMICROBIAL_DRUG)]


def test_only_the_reviewable_drug_opens_reasons(
    client,
    infection_controller_headers,
    infection_control,
    admission,
    second_antimicrobial,
):
    """Next to an exempt drug, the other one is reviewed as before"""
    _saved(client, infection_controller_headers, drugs=[second_antimicrobial])

    _prescribe_today(admission, drugs=(ANTIMICROBIAL_DRUG, second_antimicrobial))

    pendings = _open_pendings(admission)
    assert [(p["tp_pendencia"], p["fkmedicamento"]) for p in pendings] == [
        (NEVER_REVIEWED, None),
        (NO_EVALUATION, ANTIMICROBIAL_DRUG),
    ]
    record = _record(admission)
    assert record["tp_status"] == PENDING
    assert record["indicadores"]["reviewRequired"] is True
    assert {c["idDrug"]: c["reviewRequired"] for c in _summary_courses(admission)} == {
        ANTIMICROBIAL_DRUG: True,
        second_antimicrobial: False,
    }


def test_exempting_a_running_drug_settles_its_reasons_and_queues_it(
    client, infection_controller_headers, infection_control, admission
):
    """Saving queues the followed admissions running a drug the change
    concerns; their next run settles the reasons as not required"""
    _prescribe_today(admission)
    assert _record(admission)["tp_status"] == PENDING
    session.execute(
        text("DELETE FROM demo.fila_atendimento WHERE nratendimento = :admission"),
        {"admission": admission},
    )
    session_commit()

    _saved(client, infection_controller_headers, drugs=[ANTIMICROBIAL_DRUG])
    session_commit()

    queued = _queued(admission)
    assert queued is not None
    assert AdmissionQueueReasonEnum.REVIEW_EXCEPTIONS.value in queued["motivos"]

    _run_job(admission)

    assert _record(admission)["tp_status"] == REVISED
    assert _open_pendings(admission) == []
    assert {p["tp_resolucao"] for p in _pendings(admission)} == {NOT_REQUIRED}


def test_removing_the_exception_reviews_it_again(
    client, infection_controller_headers, infection_control, admission
):
    """Back off the list, the drug opens its reasons on the next run"""
    _saved(client, infection_controller_headers, drugs=[ANTIMICROBIAL_DRUG])
    _prescribe_today(admission)
    assert _open_pendings(admission) == []

    _saved(client, infection_controller_headers, drugs=[])
    _run_job(admission)

    assert [p["tp_pendencia"] for p in _open_pendings(admission)] == [
        NEVER_REVIEWED,
        NO_EVALUATION,
    ]
    assert _record(admission)["tp_status"] == PENDING


def test_an_exempt_drug_may_still_be_evaluated(
    client, infection_controller_headers, infection_control, admission
):
    """The review stays available for an exempt course; the admission page
    tells it needs no review"""
    _saved(client, infection_controller_headers, drugs=[ANTIMICROBIAL_DRUG])
    _prescribe_today(admission)

    response = _review(
        client,
        infection_controller_headers,
        admission,
        evaluations=[ANTIMICROBIAL_DRUG],
    )

    assert response.status_code == status.HTTP_200_OK, response.get_json()
    state = client.get(
        f"/infection-control/admission/{admission}",
        headers=infection_controller_headers,
    ).get_json()["data"]
    (course,) = state["courses"]
    assert course["reviewRequired"] is False
    assert course["evaluation"] is not None
    assert _record(admission)["tp_status"] == REVISED


def test_finished_course_keeps_its_flag(
    client, infection_controller_headers, infection_control, admission
):
    """Once a course ended, the summary keeps whether it needed review: a
    later change of the list doesn't rewrite what was measured"""
    _saved(client, infection_controller_headers, drugs=[ANTIMICROBIAL_DRUG])
    _prescribe(admission, _day(-6), _day(-4))
    _prescribe_today(admission)
    courses = _summary_courses(admission)
    assert [c["reviewRequired"] for c in courses] == [False, False]
    assert [c["ongoing"] for c in courses] == [False, True]

    _saved(client, infection_controller_headers, drugs=[])
    _run_job(admission)

    assert [c["reviewRequired"] for c in _summary_courses(admission)] == [False, True]


# --- prescalc and the worklist ---


def test_prescalc_follows_only_exempt_drugs_revised(
    client, infection_controller_headers, infection_control, admission
):
    """Prescalc still follows the admission (its summary feeds DOT/LOT), but
    revised, without the never reviewed reason, hidden from the worklist"""
    _saved(client, infection_controller_headers, drugs=[ANTIMICROBIAL_DRUG])

    _prescribe_today(admission, job=False)

    record = _record(admission)
    assert record["tp_status"] == REVISED
    assert record["indicadores"] == {"reviewRequired": False}
    assert _open_pendings(admission) == []
    assert admission not in _worklist(client, infection_controller_headers)


def test_worklist_hides_records_without_review_unless_asked(
    client,
    infection_controller_headers,
    infection_control,
    admission,
    second_admission,
    second_antimicrobial,
):
    """Hidden by default; shown when asked, or asked by number"""
    _saved(client, infection_controller_headers, drugs=[second_antimicrobial])
    _prescribe_today(admission, drugs=(second_antimicrobial,))
    _prescribe_today(second_admission)

    listed = _worklist(client, infection_controller_headers)
    assert admission not in listed
    assert second_admission in listed

    listed = _worklist(client, infection_controller_headers, includeNotRequired=True)
    assert {admission, second_admission} <= listed

    assert _worklist(
        client, infection_controller_headers, admissionNumbers=[admission]
    ) == {admission}


def test_prescalc_with_a_reviewable_drug_follows_as_before(
    client,
    infection_controller_headers,
    infection_control,
    admission,
    second_antimicrobial,
):
    """One reviewable antimicrobial is enough"""
    _saved(client, infection_controller_headers, drugs=[second_antimicrobial])

    id_prescription = _prescribe(
        admission, _day(-1), _day(1), drugs=(ANTIMICROBIAL_DRUG, second_antimicrobial)
    )
    _prescalc(id_prescription)

    assert _record(admission)["tp_status"] == PENDING
    assert [p["tp_pendencia"] for p in _open_pendings(admission)] == [NEVER_REVIEWED]
