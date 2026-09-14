"""Tests: the drug summary the transcription screen loads

``GET /drugs/summary/<idSegment>/<idDrug>`` is the *complete* flavour of
``drug_service.get_drug_summary``: unlike ``GET /drugs/resources`` (covered by
``test_drug_form_resources.py``) it offers only what was already prescribed —
no measure-unit or frequency catalogue — and in exchange it computes the two
fields the catalogue route always leaves empty:

* ``routes`` — the routes used for that drug/segment in the last 15 days,
  falling back to the routes configured in the ``map-routes`` memory when the
  drug has no recent history;
* ``intervals`` — the schedules used in the same window, each rendered as
  readable text, unless the ``transcription-remove-fields`` memory hides the
  field.

Fixtures use the reserved id ranges wiped by ``tests/conftest.py``: drugs and
aggregates >= 90000, prescriptions from ``test_counters`` (>= 100000) and
their items from the >= 100000001 range.
"""

import json
from contextlib import contextmanager
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from models.enums import MemoryEnum
from models.main import Drug, PrescriptionAgg
from tests.conftest import session, session_commit
from tests.utils.utils_test_prescription import (
    create_prescription,
    create_prescription_drug,
    test_counters,
)
from tests.utils.utils_test_unit_conversion import (
    create_test_drug,
    create_test_substance,
)

URL = "/drugs/summary"

SEGMENT = 1
OTHER_SEGMENT = 2
HOSPITAL = 1

# reserved ids, cleaned by tests/conftest.py::_cleanup (>= 90000)
SUMMARY_DRUG = 90601
SUMMARY_SUBSTANCE = 90601
# a second drug, with aggregated history but no prescriptions in the window
UNPRESCRIBED_DRUG = 90602
UNPRESCRIBED_SUBSTANCE = 90602
# a third drug, prescribed inside the window but with no schedule
ROUTE_ONLY_DRUG = 90603
ROUTE_ONLY_SUBSTANCE = 90603

# seed catalogue entries used by the aggregate row
UNIT_MG = "1"
FREQUENCY_8H = "3"

# the routes query only looks at the last 15 days
INSIDE_WINDOW = datetime.now() - timedelta(days=2)
OUTSIDE_WINDOW = datetime.now() - timedelta(days=40)


def _get(client, headers, id_drug=SUMMARY_DRUG, id_segment=SEGMENT):
    return client.get(f"{URL}/{id_segment}/{id_drug}", headers=headers)


@contextmanager
def _memory(kind: str, value: str | None):
    """Make the demo schema hold exactly the given memory record for this kind.

    ``value`` of ``None`` leaves the kind unset. Whatever the schema had is put
    back on exit, so the surrounding session keeps its seed data and a re-run
    never stacks duplicates (``get_memory`` reads a single row per kind).
    """
    previous = [
        row[0]
        for row in session.execute(
            text("SELECT valor FROM demo.memoria WHERE tipo = :kind"), {"kind": kind}
        ).all()
    ]

    _delete_memory(kind)
    if value is not None:
        _insert_memory(kind, value)

    try:
        yield
    finally:
        _delete_memory(kind)
        for restored in previous:
            _insert_memory(kind, json.dumps(restored))


def _insert_memory(kind: str, value: str):
    session.execute(
        text(
            "INSERT INTO demo.memoria (tipo, valor, update_at, update_by) "
            "VALUES (:kind, CAST(:value AS json), now(), 1)"
        ),
        {"kind": kind, "value": value},
    )
    session_commit()


def _delete_memory(kind: str):
    session.execute(text("DELETE FROM demo.memoria WHERE tipo = :kind"), {"kind": kind})
    session_commit()


def _create_drug_with_history(id_drug: int, id_substance: int, name: str):
    """A drug carrying one aggregate row: 5 prescriptions in 'mg' at '8h/8h'."""
    session.query(PrescriptionAgg).filter(PrescriptionAgg.idDrug == id_drug).delete()
    session.query(Drug).filter(Drug.id == id_drug).delete()
    session_commit()

    create_test_substance(id=id_substance, name=f"Substancia {name}")
    create_test_drug(id=id_drug, name=name, sctid=id_substance)

    agg = PrescriptionAgg()
    agg.idHospital = HOSPITAL
    agg.idDepartment = 1
    agg.idSegment = SEGMENT
    agg.idDrug = id_drug
    agg.idMeasureUnit = UNIT_MG
    agg.idFrequency = FREQUENCY_8H
    agg.dose = 10
    agg.frequency = 3
    agg.countNum = 5

    session.add(agg)
    session_commit()


def _prescribe(id_drug: int, date: datetime, items: list[dict], id_segment=SEGMENT):
    """Create one prescription dated ``date`` holding the given items.

    Each item is the ``route``/``interval``/``idFrequency`` of a presmed row.
    """
    id_prescription = test_counters["id_prescription"]
    admission_number = test_counters["admission_number"]
    test_counters["id_prescription"] += 1
    test_counters["admission_number"] += 1

    create_prescription(
        id=id_prescription,
        admissionNumber=admission_number,
        idPatient=id_prescription,
        idSegment=id_segment,
        date=date,
        expire=date + timedelta(days=1),
    )

    for order, item in enumerate(items, start=1):
        create_prescription_drug(
            id=int(f"{id_prescription}{order:03d}"),
            idPrescription=id_prescription,
            idDrug=id_drug,
            idSegment=id_segment,
            route=item.get("route"),
            interval=item.get("interval"),
            idFrequency=item.get("idFrequency", FREQUENCY_8H),
        )

    return id_prescription


# the fixtures are module scoped: every prescription they create lives in the
# demo schema until the session-scoped cleanup runs, so they are built once
# instead of once per test


@pytest.fixture(scope="module")
def summary_drug():
    """A drug prescribed twice inside the window and once well before it."""
    _create_drug_with_history(SUMMARY_DRUG, SUMMARY_SUBSTANCE, "Medicamento Resumo")

    _prescribe(
        SUMMARY_DRUG,
        INSIDE_WINDOW,
        [
            {"route": "VO", "interval": "8"},
            {"route": "SNE", "interval": "8 14 20"},
        ],
    )
    _prescribe(SUMMARY_DRUG, OUTSIDE_WINDOW, [{"route": "IV", "interval": "22"}])

    return SUMMARY_DRUG


@pytest.fixture(scope="module")
def unprescribed_drug():
    """A drug with aggregated history but nothing prescribed in the window."""
    _create_drug_with_history(
        UNPRESCRIBED_DRUG, UNPRESCRIBED_SUBSTANCE, "Medicamento Sem Prescricao"
    )

    return UNPRESCRIBED_DRUG


@pytest.fixture(scope="module")
def route_only_drug():
    """A drug prescribed inside the window, with a route but no schedule."""
    _create_drug_with_history(
        ROUTE_ONLY_DRUG, ROUTE_ONLY_SUBSTANCE, "Medicamento Sem Horario"
    )

    _prescribe(ROUTE_ONLY_DRUG, INSIDE_WINDOW, [{"route": "VO", "interval": None}])

    return ROUTE_ONLY_DRUG


def test_drug_summary_returns_the_drug_and_what_was_already_prescribed(
    client, analyst_headers, summary_drug
):
    """GET /drugs/summary - devolve o medicamento e apenas as unidades e frequências já prescritas"""
    response = _get(client, analyst_headers, id_drug=summary_drug)

    assert response.status_code == 200

    data = response.get_json()["data"]
    assert data["drug"] == {"id": summary_drug, "name": "Medicamento Resumo"}

    # the catalogue is not appended here, unlike GET /drugs/resources
    assert data["units"] == [{"id": UNIT_MG, "description": "mg", "amount": 5}]
    assert data["frequencies"] == [
        {"id": FREQUENCY_8H, "description": "8h/8h", "amount": 5}
    ]


def test_drug_summary_returns_the_recently_prescribed_routes(
    client, analyst_headers, summary_drug
):
    """GET /drugs/summary - lista as vias usadas nos últimos 15 dias"""
    data = _get(client, analyst_headers, id_drug=summary_drug).get_json()["data"]

    assert sorted(r["id"] for r in data["routes"]) == ["SNE", "VO"]
    # the route is its own description: there is no catalogue behind it
    assert all(r["id"] == r["description"] for r in data["routes"])


def test_drug_summary_ignores_routes_prescribed_before_the_window(
    client, analyst_headers, summary_drug
):
    """GET /drugs/summary - desconsidera as vias prescritas fora da janela de 15 dias"""
    data = _get(client, analyst_headers, id_drug=summary_drug).get_json()["data"]

    assert "IV" not in [r["id"] for r in data["routes"]]


def test_drug_summary_ignores_the_history_of_another_segment(
    client, analyst_headers, summary_drug
):
    """GET /drugs/summary - desconsidera o histórico de outro segmento"""
    data = _get(
        client, analyst_headers, id_drug=summary_drug, id_segment=OTHER_SEGMENT
    ).get_json()["data"]

    assert data["units"] == []
    assert data["frequencies"] == []
    assert data["intervals"] == []


def test_drug_summary_falls_back_to_the_map_routes_memory(
    client, analyst_headers, unprescribed_drug
):
    """GET /drugs/summary - sem histórico recente, usa as vias configuradas na memória map-routes"""
    with _memory(
        MemoryEnum.MAP_ROUTES.value,
        '[{"id": "VO", "value": "Via Oral"}, {"id": "IV", "value": "Intravenosa"}]',
    ):
        data = _get(client, analyst_headers, id_drug=unprescribed_drug).get_json()[
            "data"
        ]

    assert data["routes"] == [
        {"id": "VO", "description": "Via Oral"},
        {"id": "IV", "description": "Intravenosa"},
    ]


def test_drug_summary_skips_malformed_map_routes_entries(
    client, analyst_headers, unprescribed_drug
):
    """GET /drugs/summary - ignora entradas malformadas da memória map-routes"""
    with _memory(
        MemoryEnum.MAP_ROUTES.value,
        '["VO", {"id": "IV", "value": "Intravenosa"}]',
    ):
        data = _get(client, analyst_headers, id_drug=unprescribed_drug).get_json()[
            "data"
        ]

    assert data["routes"] == [{"id": "IV", "description": "Intravenosa"}]


def test_drug_summary_returns_no_routes_without_history_or_memory(
    client, analyst_headers, unprescribed_drug
):
    """GET /drugs/summary - sem histórico recente e sem memória, as vias voltam vazias"""
    with _memory(MemoryEnum.MAP_ROUTES.value, None):
        data = _get(client, analyst_headers, id_drug=unprescribed_drug).get_json()[
            "data"
        ]

    assert data["routes"] == []


def test_drug_summary_prefers_the_prescribed_routes_over_the_memory(
    client, analyst_headers, summary_drug
):
    """GET /drugs/summary - havendo histórico recente, a memória map-routes não é usada"""
    with _memory(
        MemoryEnum.MAP_ROUTES.value, '[{"id": "IM", "value": "Intramuscular"}]'
    ):
        data = _get(client, analyst_headers, id_drug=summary_drug).get_json()["data"]

    assert sorted(r["id"] for r in data["routes"]) == ["SNE", "VO"]


def test_drug_summary_renders_the_recently_prescribed_intervals(
    client, analyst_headers, summary_drug
):
    """GET /drugs/summary - lista os horários recentes já formatados para leitura"""
    data = _get(client, analyst_headers, id_drug=summary_drug).get_json()["data"]

    assert {i["id"]: i["description"] for i in data["intervals"]} == {
        "8": "Às 8 Horas",
        "8 14 20": "às 8h, às 14h, às 20h",
    }
    assert {i["idFrequency"] for i in data["intervals"]} == {FREQUENCY_8H}


def test_drug_summary_ignores_intervals_prescribed_before_the_window(
    client, analyst_headers, summary_drug
):
    """GET /drugs/summary - desconsidera os horários prescritos fora da janela de 15 dias"""
    data = _get(client, analyst_headers, id_drug=summary_drug).get_json()["data"]

    assert "22" not in [i["id"] for i in data["intervals"]]


def test_drug_summary_ignores_items_without_interval(
    client, analyst_headers, route_only_drug
):
    """GET /drugs/summary - itens sem horário não entram na lista"""
    data = _get(client, analyst_headers, id_drug=route_only_drug).get_json()["data"]

    assert data["routes"] == [{"id": "VO", "description": "VO"}]
    assert data["intervals"] == []


def test_drug_summary_omits_intervals_when_the_memory_removes_the_field(
    client, analyst_headers, summary_drug
):
    """GET /drugs/summary - horários não são calculados quando a memória remove o campo"""
    with _memory(MemoryEnum.TRANSCRIPTION_REMOVE_FIELDS.value, '["interval"]'):
        data = _get(client, analyst_headers, id_drug=summary_drug).get_json()["data"]

    assert data["removeFields"] == ["interval"]
    assert data["intervals"] == []
    # removing the field does not affect the routes
    assert sorted(r["id"] for r in data["routes"]) == ["SNE", "VO"]


def test_drug_summary_keeps_intervals_when_another_field_is_removed(
    client, analyst_headers, summary_drug
):
    """GET /drugs/summary - remover outro campo não esconde os horários"""
    with _memory(MemoryEnum.TRANSCRIPTION_REMOVE_FIELDS.value, '["route"]'):
        data = _get(client, analyst_headers, id_drug=summary_drug).get_json()["data"]

    assert data["removeFields"] == ["route"]
    assert [i["id"] for i in data["intervals"]] != []


def test_drug_summary_returns_the_configured_transcription_fields(
    client, analyst_headers, summary_drug
):
    """GET /drugs/summary - devolve os campos extras configurados na memória"""
    with _memory(MemoryEnum.TRANSCRIPTION_FIELDS.value, '["dose", "peso"]'):
        data = _get(client, analyst_headers, id_drug=summary_drug).get_json()["data"]

    assert data["extraFields"] == ["dose", "peso"]


def test_drug_summary_returns_an_empty_name_for_an_unknown_drug(
    client, analyst_headers
):
    """GET /drugs/summary - medicamento inexistente devolve nome vazio e o id informado"""
    response = _get(client, analyst_headers, id_drug=999999)

    assert response.status_code == 200

    data = response.get_json()["data"]
    assert data["drug"] == {"id": 999999, "name": ""}
    assert data["units"] == []
    assert data["frequencies"] == []
    assert data["intervals"] == []


def test_drug_summary_requires_prescription_read_permission(
    client, user_manager_headers
):
    """GET /drugs/summary - deve retornar erro [401 UNAUTHORIZED] sem permissão de leitura de prescrição"""
    assert _get(client, user_manager_headers).status_code == 401
