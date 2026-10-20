"""Tests: infection control follow-up, the admission state and the worklist"""

from datetime import datetime, timedelta

from sqlalchemy import text

from models.main import db
from services.infection_control import infection_control_service
from tests.conftest import session, session_commit
from tests.integration.infection_control.helpers import (
    ADULT_SEGMENT,
    ANTIMICROBIAL_DRUG,
    CLOSED,
    CPOE_SEGMENT,
    DEPARTMENT_BY_SEGMENT,
    NEVER_REVIEWED,
    NO_EVALUATION,
    OTHER_ADULT_DEPARTMENT,
    OTHER_DRUG,
    PATIENT_ID,
    PENDING,
    REVISED,
    SCHEDULED_DATE,
    _day,
    _prescalc,
    _prescribe,
    _prescribe_today,
    _run_job,
    _set,
)
from utils import status


def test_state_requires_permission(client, analyst_headers, admission):
    """401 without READ_INFECTION_CONTROL, even with READ_PRESCRIPTION"""
    response = client.get(
        f"/infection-control/admission/{admission}", headers=analyst_headers
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_state_without_feature(client, infection_controller_headers, admission):
    """The page learns the feature is off"""
    response = client.get(
        f"/infection-control/admission/{admission}",
        headers=infection_controller_headers,
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"]["enabled"] is False


def test_state_of_followed_admission(
    client, infection_controller_headers, infection_control, admission
):
    """Status, open reasons and the courses of a followed admission"""
    _prescribe_today(admission)

    response = client.get(
        f"/infection-control/admission/{admission}",
        headers=infection_controller_headers,
    )

    data = response.get_json()["data"]
    assert data["followed"] is True
    assert data["status"] == PENDING
    assert [p["type"] for p in data["pendings"]] == [NEVER_REVIEWED, NO_EVALUATION]
    assert data["courses"][0]["evaluation"] is None


def _view(client, headers, admission):
    """The infection control page of an admission: timeline and follow-up"""
    response = client.get(
        f"/infection-control/antimicrobial-timeline/{admission}", headers=headers
    )
    assert response.status_code == status.HTTP_200_OK
    return response.get_json()["data"]


def test_view_without_feature(client, infection_controller_headers, admission):
    """The page loads its timeline and learns the feature is off"""
    _prescribe_today(admission, job=False)

    data = _view(client, infection_controller_headers, admission)

    assert len(data["courses"]) == 1
    assert data["followUp"] == {"enabled": False, "admissionNumber": admission}


def test_view_brings_follow_up(
    client, infection_controller_headers, infection_control, admission
):
    """The timeline comes with the follow-up, both from the same courses"""
    _prescribe_today(admission)

    data = _view(client, infection_controller_headers, admission)

    follow_up = data["followUp"]
    assert follow_up["followed"] is True
    assert follow_up["status"] == PENDING
    # the page places each evaluation on the course with the same drug and start
    assert [(c["idDrug"], c["start"]) for c in follow_up["courses"]] == [
        (c["idDrug"], c["start"]) for c in data["courses"]
    ]


def test_view_survives_follow_up_failure(
    client, infection_controller_headers, infection_control, admission, monkeypatch
):
    """A failing follow-up (here a query error) still lets the timeline
    through, without the follow-up"""
    _prescribe_today(admission)

    def failing_state(**kwargs):
        db.session.execute(text("SELECT 1 / 0"))

    monkeypatch.setattr(infection_control_service, "_get_state", failing_state)

    data = _view(client, infection_controller_headers, admission)

    assert len(data["courses"]) == 1
    assert data["followUp"] is None


def test_worklist_requires_permission(
    client, analyst_headers, infection_control, admission
):
    """401 without READ_INFECTION_CONTROL, even with READ_PRESCRIPTION"""
    _prescribe_today(admission)

    response = client.post(
        "/infection-control/admissions",
        json={"status": [PENDING], "limit": 500},
        headers=analyst_headers,
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_worklist_lists_pending_admission(
    client, infection_controller_headers, infection_control, admission
):
    """The worklist brings the admission with its open reasons"""
    _prescribe_today(admission)

    response = client.post(
        "/infection-control/admissions",
        json={"status": [PENDING], "limit": 500},
        headers=infection_controller_headers,
    )

    assert response.status_code == status.HTTP_200_OK
    rows = [
        a
        for a in response.get_json()["data"]["admissions"]
        if a["admissionNumber"] == admission
    ]
    assert len(rows) == 1
    assert rows[0]["idPatient"] == str(PATIENT_ID)
    assert [p["type"] for p in rows[0]["pendings"]] == [NEVER_REVIEWED, NO_EVALUATION]


def _worklist(client, headers, admission, **filters):
    """The worklist narrowed to one admission, plus the given filters"""
    response = client.post(
        "/infection-control/admissions",
        json={"status": [PENDING], "admissionNumbers": [admission], **filters},
        headers=headers,
    )
    assert response.status_code == status.HTTP_200_OK
    return response.get_json()["data"]


def test_worklist_filters_by_department(
    client, infection_controller_headers, infection_control, admission
):
    """The department of the latest prescription narrows the worklist"""
    _prescribe_today(admission)

    def listed(**filters):
        data = _worklist(client, infection_controller_headers, admission, **filters)
        return [a["admissionNumber"] for a in data["admissions"]]

    assert listed(idDepartment=[DEPARTMENT_BY_SEGMENT[ADULT_SEGMENT]]) == [admission]
    assert listed(idDepartment=[DEPARTMENT_BY_SEGMENT[CPOE_SEGMENT]]) == []


def test_worklist_follows_patient_to_another_department(
    client, infection_controller_headers, infection_control, admission
):
    """The department filtered by and the bed and department shown are those
    of the latest prescription-day, as the patient moves"""
    _prescribe_today(admission)
    _prescalc(
        _prescribe(
            admission,
            _day(0),
            _day(1),
            drugs=(OTHER_DRUG,),
            id_department=OTHER_ADULT_DEPARTMENT,
            bed="202",
        )
    )
    # the move is a new prescription-day: the job points the record at it
    _run_job(admission)

    def listed(**filters):
        data = _worklist(client, infection_controller_headers, admission, **filters)
        return [a["admissionNumber"] for a in data["admissions"]]

    assert listed(idDepartment=[OTHER_ADULT_DEPARTMENT]) == [admission]
    assert listed(idDepartment=[DEPARTMENT_BY_SEGMENT[ADULT_SEGMENT]]) == []

    [row] = _worklist(client, infection_controller_headers, admission)["admissions"]
    assert row["bed"] == "202"
    assert row["department"] == "Setor Adulto 2"


def test_worklist_lists_record_not_pointed_yet(
    client, infection_controller_headers, infection_control, admission
):
    """A record not pointed at a prescription yet is listed, without bed and
    department, and left out by the department filter"""
    _prescribe_today(admission)
    _set("ci_atendimento", admission, fkprescricao_ultima=None)

    [row] = _worklist(client, infection_controller_headers, admission)["admissions"]
    assert row["admissionNumber"] == admission
    assert row["bed"] is None
    assert row["department"] is None

    data = _worklist(
        client,
        infection_controller_headers,
        admission,
        idDepartment=[DEPARTMENT_BY_SEGMENT[ADULT_SEGMENT]],
    )
    assert data["admissions"] == []


def test_worklist_filters_by_pending_type(
    client, infection_controller_headers, infection_control, admission
):
    """Only admissions with an open reason of the chosen types"""
    _prescribe_today(admission)

    def listed(**filters):
        data = _worklist(client, infection_controller_headers, admission, **filters)
        return [a["admissionNumber"] for a in data["admissions"]]

    assert listed(pendingTypes=[NO_EVALUATION]) == [admission]
    assert listed(pendingTypes=[SCHEDULED_DATE, NO_EVALUATION]) == [admission]
    assert listed(pendingTypes=[SCHEDULED_DATE]) == []


def test_worklist_counts_the_matching_admissions(
    client, infection_controller_headers, infection_control, admission
):
    """count is every admission matching the filters and statuses, beyond
    the limit"""
    _prescribe_today(admission)

    def worklist(statuses, limit=500):
        return client.post(
            "/infection-control/admissions",
            json={
                "status": statuses,
                "admissionNumbers": [admission],
                "limit": limit,
            },
            headers=infection_controller_headers,
        ).get_json()["data"]

    assert worklist([PENDING])["count"] == 1
    assert worklist([REVISED, CLOSED])["count"] == 0
    assert worklist([PENDING, REVISED])["count"] == 1

    # a page past the admissions still counts them all
    past = client.post(
        "/infection-control/admissions",
        json={"status": [PENDING], "admissionNumbers": [admission], "offset": 1},
        headers=infection_controller_headers,
    ).get_json()["data"]
    assert past["admissions"] == []
    assert past["count"] == 1


def test_worklist_counts_up_to_the_count_limit(
    client,
    infection_controller_headers,
    infection_control,
    admission,
    second_admission,
    monkeypatch,
):
    """Only a list cut by the limit counts its matches, up to COUNT_LIMIT, and
    says when more match"""
    _prescribe_today(admission)
    _prescribe_today(second_admission)

    def worklist(limit):
        return client.post(
            "/infection-control/admissions",
            json={
                "status": [PENDING],
                "admissionNumbers": [admission, second_admission],
                "limit": limit,
            },
            headers=infection_controller_headers,
        ).get_json()["data"]

    def fail(*args, **kwargs):
        raise RuntimeError("counted a list holding every match")

    with monkeypatch.context() as patch:
        patch.setattr(
            "repository.infection_control.infection_control_repository"
            ".count_admissions",
            fail,
        )
        data = worklist(limit=500)
    assert len(data["admissions"]) == 2
    assert data["count"] == 2
    assert data["countLimited"] is False

    data = worklist(limit=1)
    assert len(data["admissions"]) == 1
    assert data["count"] == 2
    assert data["countLimited"] is False

    monkeypatch.setattr(infection_control_service, "COUNT_LIMIT", 1)
    data = worklist(limit=1)
    assert data["count"] == 1
    assert data["countLimited"] is True


def test_worklist_filters_overdue_review(
    client, infection_controller_headers, infection_control, admission
):
    """Only admissions whose scheduled review date has passed"""
    _prescribe_today(admission)

    def listed():
        data = _worklist(
            client, infection_controller_headers, admission, overdueReview=True
        )
        return [a["admissionNumber"] for a in data["admissions"]]

    # no review scheduled
    assert listed() == []

    for offset, expected in ((1, []), (-1, [admission])):
        session.execute(
            text(
                "UPDATE demo.ci_atendimento SET dt_proxima_revisao = :date "
                "WHERE nratendimento = :admission"
            ),
            {"date": datetime.now() + timedelta(days=offset), "admission": admission},
        )
        session_commit()
        assert listed() == expected


def _close(admission_number, days_ago):
    """Close the admission record as of some days ago"""
    _set(
        "ci_atendimento",
        admission_number,
        tp_status=CLOSED,
        dt_status=datetime.now() - timedelta(days=days_ago),
    )


def test_worklist_lists_closed_within_closed_days(
    client, infection_controller_headers, infection_control, admission
):
    """Closed admissions are listed only within closedDays of closing (30 by
    default), unless asked by admission number"""
    _prescribe_today(admission)
    _close(admission, days_ago=40)

    def listed(**filters):
        response = client.post(
            "/infection-control/admissions",
            json={"status": [CLOSED], "limit": 500, **filters},
            headers=infection_controller_headers,
        )
        assert response.status_code == status.HTTP_200_OK
        return [
            a["admissionNumber"]
            for a in response.get_json()["data"]["admissions"]
            if a["admissionNumber"] == admission
        ]

    assert listed() == []
    assert listed(closedDays=60) == [admission]
    assert listed(admissionNumbers=[admission]) == [admission]


def test_worklist_leaves_closed_out_of_open_only_filters(
    client,
    infection_controller_headers,
    infection_control,
    admission,
    second_admission,
):
    """A closed record has nothing running, no open reason and no evaluation
    in force: the filters asking for them leave the closed ones out without
    looking at them, even when the record still keeps what it last saw"""
    _prescribe_today(admission)
    _prescribe_today(second_admission)
    # closed by hand, so its indicadores still have the running course
    _close(admission, days_ago=1)

    def listed(statuses, **filters):
        response = client.post(
            "/infection-control/admissions",
            json={
                "status": statuses,
                "admissionNumbers": [admission, second_admission],
                **filters,
            },
            headers=infection_controller_headers,
        )
        assert response.status_code == status.HTTP_200_OK
        return [a["admissionNumber"] for a in response.get_json()["data"]["admissions"]]

    assert listed([CLOSED]) == [admission]
    assert listed([CLOSED], antimicrobials=[{"idDrug": [ANTIMICROBIAL_DRUG]}]) == []
    assert listed([CLOSED], awareLevels=[1, 2, 3]) == []
    assert listed([CLOSED], pendingTypes=[NO_EVALUATION]) == []
    assert listed([CLOSED], nonConforming=True) == []
    # a criterion asking for nothing asks for nothing of the closed ones either
    assert listed([CLOSED], antimicrobials=[{"treatmentDayFrom": 1}]) == [admission]
    assert listed([PENDING, CLOSED], pendingTypes=[NO_EVALUATION]) == [second_admission]


def test_worklist_lists_open_first_and_latest_closed_first(
    client,
    infection_controller_headers,
    infection_control,
    admission,
    second_admission,
    third_admission,
):
    """The open admissions come first, longest in their status first, then the
    closed ones, latest closed first"""
    for admission_number in (admission, second_admission, third_admission):
        _prescribe_today(admission_number)
    _close(second_admission, days_ago=5)
    _close(third_admission, days_ago=1)

    response = client.post(
        "/infection-control/admissions",
        json={
            "status": [PENDING, REVISED, CLOSED],
            "admissionNumbers": [admission, second_admission, third_admission],
        },
        headers=infection_controller_headers,
    )

    assert response.status_code == status.HTTP_200_OK
    assert [
        a["admissionNumber"] for a in response.get_json()["data"]["admissions"]
    ] == [
        admission,
        third_admission,
        second_admission,
    ]


def test_worklist_asks_for_more_filters_when_too_slow(
    client, infection_controller_headers, infection_control, admission, monkeypatch
):
    """A worklist query that outlasts its timeout is stopped, and the user is
    asked for more filters instead of waiting for the request to time out"""
    _prescribe_today(admission)

    def slow(*args, **kwargs):
        db.session.execute(text("SELECT pg_sleep(1)"))

    monkeypatch.setattr(infection_control_service, "WORKLIST_STATEMENT_TIMEOUT_MS", 100)
    monkeypatch.setattr(
        "repository.infection_control.infection_control_repository.list_admissions",
        slow,
    )

    started = datetime.now()
    response = client.post(
        "/infection-control/admissions",
        json={"status": [PENDING], "admissionNumbers": [admission]},
        headers=infection_controller_headers,
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.queryTimeout"
    assert datetime.now() - started < timedelta(seconds=1)
