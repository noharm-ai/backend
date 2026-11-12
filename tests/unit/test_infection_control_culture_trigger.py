"""Unit tests for the culture trigger of the infection control evaluations
(services.infection_control.culture_trigger_service) and how the rule
(plan_rule) opens its reason.

An evaluation watching cultures (CULTURE_RESULT among its triggers) opens a
reason of its drug when a culture result is released after it was made. Only
released results of the DynamoDB culture summary count, as the protocol
variable cultureReleaseTime reads them.
"""

import time
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from models.enums import InfectionControlPendingTypeEnum
from repository import culture_repository
from services.infection_control import antimicrobial_timeline_service as timeline
from services.infection_control import culture_trigger_service as culture_trigger
from services.infection_control import infection_control_status_service as rule

NOW = datetime(2026, 10, 7, 14, 0)
EVALUATED_AT = NOW - timedelta(days=1)
CULTURE_RESULT = InfectionControlPendingTypeEnum.CULTURE_RESULT.value
EXPIRED = InfectionControlPendingTypeEnum.EXPIRED.value


def _evaluation(triggers=(CULTURE_RESULT,), created_at=EVALUATED_AT, id_drug=1):
    """An active evaluation of drug 1's running course"""
    return SimpleNamespace(
        id=7,
        id_drug=id_drug,
        course_start=NOW - timedelta(days=2, hours=6),
        valid_until=NOW + timedelta(days=7),
        posology=None,
        triggers=list(triggers),
        created_at=created_at,
    )


def _course(id_drug=1):
    """A daily course of one drug running since two days ago"""
    rows = [
        SimpleNamespace(
            id_prescription=10 + day,
            id_prescription_drug=100 + day,
            id_drug=id_drug,
            drug=f"DRUG {id_drug}",
            id_substance=None,
            substance=None,
            atb_level=None,
            date=NOW - timedelta(days=day, hours=6),
            expire=NOW - timedelta(days=day) + timedelta(hours=18),
            suspended_date=None,
            cpoe=False,
            dose=2.0,
            doseconv=2.0,
            measure_unit="g",
            frequency="8/8h",
            daily_frequency=3.0,
            route="EV",
            period_total=None,
            id_measure_unit="g",
            default_measure_unit=None,
            use_weight=None,
            notes=None,
        )
        for day in (2, 1, 0)
    ]
    (course,) = timeline.group_courses([timeline.build_item(r, now=NOW) for r in rows])
    return course


def _summary_item(release_date, result="R", arrival=None, **kwargs):
    """An item of the culture summary as culture_service groups it"""
    return {
        "material": kwargs.get("material", "URINA"),
        "microorganism": kwargs.get("microorganism", "E. COLI"),
        "result": result,
        "releaseDate": release_date.isoformat() if release_date else None,
        "resultArrival": arrival.isoformat() if arrival else None,
    }


def _summary(*items, drug="AMICACINA"):
    """The culture summary of the patient (one drug)"""
    return [{"drug": drug, "items": list(items)}]


def _released(*items, **kwargs):
    """The released cultures of a summary"""
    return culture_trigger.released_cultures(_summary(*items, **kwargs))


def _plan(evaluation, cultures):
    """Plan a reviewed admission with drug 1 running and its evaluation"""
    return rule.plan_rule(
        now=NOW,
        ongoing=[_course()],
        discharged=False,
        id_last_review=3,
        active_evaluations=[evaluation],
        open_pendings=[],
        cultures=cultures,
    )


def test_an_optional_trigger_settled_by_a_new_evaluation():
    """The review accepts it among the optional triggers, and a new
    evaluation of the drug settles its reason"""
    assert CULTURE_RESULT in rule.OPTIONAL_TRIGGERS
    assert CULTURE_RESULT in rule.EVALUATION_RESOLVED_TYPES


def test_a_result_released_after_the_evaluation_opens_a_reason():
    """The reason names the new culture"""
    released = NOW - timedelta(hours=2)
    plan = _plan(_evaluation(), _released(_summary_item(released)))

    (pending,) = plan.open_pendings
    assert pending["pending_type"] == InfectionControlPendingTypeEnum.CULTURE_RESULT
    assert pending["id_drug"] == 1
    assert pending["id_evaluation"] == 7
    assert pending["details"] == {
        "drug": "DRUG 1",
        "releaseDate": released.isoformat(),
        "cultures": [
            {
                "material": "URINA",
                "microorganism": "E. COLI",
                "releaseDate": released.isoformat(),
            }
        ],
    }


@pytest.mark.parametrize(
    "item",
    [
        # released before the evaluation: the reviewer could see it
        _summary_item(EVALUATED_AT - timedelta(hours=1)),
        # released at the very moment of the evaluation
        _summary_item(EVALUATED_AT),
        # a prediction or a collection still waiting for the lab
        _summary_item(NOW - timedelta(hours=1), result=None),
        # a release date the integration couldn't give
        _summary_item(None),
        # dated in the future
        _summary_item(NOW + timedelta(hours=1)),
    ],
)
def test_what_doesnt_open_a_reason(item):
    """Only a lab result released after the evaluation (and not after now)"""
    assert _plan(_evaluation(), _released(item)).open_pendings == []


def test_not_without_the_trigger():
    """An evaluation that didn't turn it on ignores the cultures"""
    released = _released(_summary_item(NOW - timedelta(hours=1)))
    assert _plan(_evaluation(triggers=[EXPIRED]), released).open_pendings == []


def test_not_without_cultures():
    """No culture (or no evaluation watching them: None) opens nothing"""
    assert _plan(_evaluation(), []).open_pendings == []
    assert _plan(_evaluation(), None).open_pendings == []


def test_one_entry_per_material_and_microorganism_newest_first():
    """Every drug tested against a culture has an item: the reason lists the
    culture once, with its latest release"""
    older = NOW - timedelta(hours=5)
    newer = NOW - timedelta(hours=1)
    cultures = culture_trigger.released_cultures(
        _summary(_summary_item(older), drug="AMICACINA")
        + _summary(
            _summary_item(newer),
            _summary_item(older, material="SANGUE", microorganism="S. AUREUS"),
            drug="CEFTRIAXONA",
        )
    )

    details = culture_trigger.culture_match(_evaluation(), cultures, NOW)

    assert details["releaseDate"] == newer.isoformat()
    assert details["cultures"] == [
        {
            "material": "URINA",
            "microorganism": "E. COLI",
            "releaseDate": newer.isoformat(),
        },
        {
            "material": "SANGUE",
            "microorganism": "S. AUREUS",
            "releaseDate": older.isoformat(),
        },
    ]


def test_the_listed_cultures_are_bounded():
    """A runaway integration doesn't fill the reason"""
    items = [
        _summary_item(NOW - timedelta(minutes=i + 1), microorganism=f"MO {i}")
        for i in range(culture_trigger.MAX_DETAILED_CULTURES + 5)
    ]
    details = culture_trigger.culture_match(_evaluation(), _released(*items), NOW)

    assert len(details["cultures"]) == culture_trigger.MAX_DETAILED_CULTURES
    assert details["cultures"][0]["microorganism"] == "MO 0"


def test_dates_with_an_offset_are_read_in_local_time(monkeypatch):
    """The evaluations are kept in local time (America/Sao_Paulo, UTC-3)"""
    monkeypatch.setenv("TZ", "America/Sao_Paulo")
    time.tzset()
    try:
        (culture,) = _released(
            {
                **_summary_item(None),
                "releaseDate": "2026-10-07T13:00:00+00:00",
                # the culture cache job writes the arrival in UTC
                "resultArrival": "2026-10-07T14:30:00+00:00",
            }
        )
    finally:
        monkeypatch.undo()
        time.tzset()

    assert culture.release_date == datetime(2026, 10, 7, 10, 0)
    assert culture.arrival == datetime(2026, 10, 7, 11, 30)


def test_counts_a_result_by_when_it_reached_the_summary():
    """A result released before the evaluation that reached the summary after
    it was not seen by the reviewer: it opens a reason, naming its release"""
    released = EVALUATED_AT - timedelta(hours=2)
    late = _summary_item(released, arrival=EVALUATED_AT + timedelta(minutes=2))

    (pending,) = _plan(_evaluation(), _released(late)).open_pendings
    assert pending["details"]["releaseDate"] == released.isoformat()

    # released after the evaluation but already there before it: an
    # integration clock ahead of the summary's; it was seen
    seen = _summary_item(
        EVALUATED_AT + timedelta(hours=1), arrival=EVALUATED_AT - timedelta(minutes=1)
    )
    assert _plan(_evaluation(), _released(seen)).open_pendings == []

    # without an arrival (written before it was kept) the release counts
    assert _plan(
        _evaluation(), _released(_summary_item(NOW - timedelta(hours=1)))
    ).open_pendings


def test_reads_the_summary_only_when_an_evaluation_watches_cultures(monkeypatch):
    """The DynamoDB summary is read once per run, and only when needed"""
    calls = []

    def fake_summary(schema, id_patient):
        """Record the read and answer two items of the patient"""
        calls.append((schema, id_patient))
        return [
            {
                "ativo": True,
                "nomemedicamento": "AMICACINA",
                "nomematerial": "URINA",
                "microorganismo": "E. COLI",
                "resultado": "Resistente",
                "dataliberacao": "2026-10-07T12:00:00",
            },
            # turned off by a user: the culture card leaves it out too
            {
                "ativo": False,
                "nomemedicamento": "CEFTRIAXONA",
                "resultado": "Sensível",
                "dataliberacao": "2026-10-07T13:00:00",
            },
        ]

    monkeypatch.setattr(
        culture_repository, "get_culture_summary_from_dynamodb", fake_summary
    )
    patient = SimpleNamespace(idPatient=42)

    assert (
        culture_trigger.load_cultures(
            schema="demo", evaluations=[_evaluation(triggers=[])], patient=patient
        )
        is None
    )
    assert calls == []

    assert (
        culture_trigger.load_cultures(
            schema="demo", evaluations=[_evaluation()], patient=None
        )
        == []
    )
    assert calls == []

    (culture,) = culture_trigger.load_cultures(
        schema="demo", evaluations=[_evaluation()], patient=patient
    )
    assert calls == [("demo", 42)]
    assert culture.release_date == datetime(2026, 10, 7, 12, 0)
    assert culture.material == "URINA"


def test_a_summary_that_cant_be_read_reads_as_no_culture(monkeypatch):
    """A DynamoDB failure never breaks the rule"""

    def failing(schema, id_patient):
        raise RuntimeError("dynamodb down")

    monkeypatch.setattr(
        culture_repository, "get_culture_summary_from_dynamodb", failing
    )

    assert (
        culture_trigger.load_cultures(
            schema="demo",
            evaluations=[_evaluation()],
            patient=SimpleNamespace(idPatient=42),
        )
        == []
    )
