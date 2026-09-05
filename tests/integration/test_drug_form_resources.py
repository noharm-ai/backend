"""Tests: lookup data the prescription drug form loads

Covers the three endpoints the drug form calls before it can be rendered:

* ``GET /drugs/resources/<idDrug>/<idSegment>[/<idHospital>]`` — the drug plus
  the measure-unit and frequency catalogues, annotated with how often each one
  was already prescribed for that drug/segment;
* ``GET /drugs/frequencies`` — the frequency catalogue on its own;
* ``GET /lists/routes`` — the routes configured in the ``map-routes`` memory.
"""

import json
from contextlib import contextmanager

import pytest
from sqlalchemy import text

from models.appendix import Frequency, MeasureUnit
from models.enums import MemoryEnum
from models.main import Drug, PrescriptionAgg
from security.role import Role
from tests.conftest import get_access, make_headers, session, session_commit
from tests.utils.utils_test_unit_conversion import (
    create_test_drug,
    create_test_substance,
)

RESOURCES_URL = "/drugs/resources"
FREQUENCIES_URL = "/drugs/frequencies"
ROUTES_URL = "/lists/routes"

# demo seed drug and the only segment it has aggregated data for
SEED_DRUG = 3
SEED_SEGMENT = 1
SEED_HOSPITAL = 1

# reserved ids, cleaned by tests/conftest.py::_cleanup (>= 90000)
FORM_DRUG = 90201
FORM_SUBSTANCE = 90201


def _get(client, headers, id_drug=SEED_DRUG, id_segment=SEED_SEGMENT, id_hospital=None):
    url = f"{RESOURCES_URL}/{id_drug}/{id_segment}"
    if id_hospital is not None:
        url = f"{url}/{id_hospital}"

    return client.get(url, headers=headers)


def _by_id(items, item_id):
    """Every entry of the given list matching the id (the catalogue and the
    prescribed history are concatenated, so an id can show up twice)"""
    return [i for i in items if i["id"] == item_id]


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


@pytest.fixture
def prescribed_drug():
    """A drug with aggregated history: 7 prescriptions in 'mg' at '8h/8h'"""
    session.query(PrescriptionAgg).filter(PrescriptionAgg.idDrug == FORM_DRUG).delete()
    session.query(Drug).filter(Drug.id == FORM_DRUG).delete()
    session_commit()

    create_test_substance(id=FORM_SUBSTANCE, name="Substancia Formulario")
    create_test_drug(id=FORM_DRUG, name="Medicamento Formulario", sctid=FORM_SUBSTANCE)

    agg = PrescriptionAgg()
    agg.idHospital = SEED_HOSPITAL
    agg.idDepartment = 1
    agg.idSegment = SEED_SEGMENT
    agg.idDrug = FORM_DRUG
    agg.idMeasureUnit = "1"  # mg
    agg.idFrequency = "3"  # 8h/8h
    agg.dose = 10
    agg.frequency = 3
    agg.countNum = 7

    session.add(agg)
    session_commit()

    return FORM_DRUG


def test_drug_resources_returns_the_drug_and_the_full_catalogues(
    client, analyst_headers
):
    """GET /drugs/resources - retorna o medicamento e os catálogos completos de unidades e frequências"""
    response = _get(client, analyst_headers)

    assert response.status_code == 200

    data = response.get_json()["data"]
    assert data["drug"] == {"id": SEED_DRUG, "name": "ANLODIPINO 10 mg CP"}

    # the whole catalogue is offered, not only what was already prescribed
    assert {u["description"] for u in data["units"]} == {
        "UI",
        "Un",
        "mcg",
        "mg",
        "mg/ml",
        "ml",
    }
    assert {f["description"] for f in data["frequencies"]} == {
        "1x/dia",
        "12h/12h",
        "8h/8h",
        "6h/6h",
        "4h/4h",
    }


def test_drug_resources_sorts_the_catalogues_by_description(client, analyst_headers):
    """GET /drugs/resources - ordena unidades e frequências por descrição"""
    data = _get(client, analyst_headers).get_json()["data"]

    # compared against what the database itself returns rather than against a
    # Python sort: ordering by description is the database's, and it differs
    # between collations ('UI' sorts before 'mcg' under C, after it under en_US)
    expected_units = [
        row.description
        for row in session.query(MeasureUnit).order_by(MeasureUnit.description).all()
    ]
    expected_frequencies = [
        row.description
        for row in session.query(Frequency).order_by(Frequency.description).all()
    ]

    # the catalogue is appended after the previously prescribed entries
    assert [u["description"] for u in data["units"]][
        -len(expected_units) :
    ] == expected_units
    assert [f["description"] for f in data["frequencies"]][
        -len(expected_frequencies) :
    ] == expected_frequencies


def test_drug_resources_counts_previously_prescribed_units_and_frequencies(
    client, analyst_headers, prescribed_drug
):
    """GET /drugs/resources - traz a contagem das unidades e frequências já prescritas"""
    data = _get(client, analyst_headers, id_drug=prescribed_drug).get_json()["data"]

    # 'mg' and '8h/8h' come back twice: once from the drug history carrying the
    # count, once from the catalogue with zero
    assert sorted(u["amount"] for u in _by_id(data["units"], "1")) == [0, 7]
    assert sorted(f["amount"] for f in _by_id(data["frequencies"], "3")) == [0, 7]

    # a unit that was never prescribed for this drug only shows the zeroed entry
    assert [u["amount"] for u in _by_id(data["units"], "4")] == [0]


def test_drug_resources_ignores_history_of_another_segment(
    client, analyst_headers, prescribed_drug
):
    """GET /drugs/resources - desconsidera o histórico de outro segmento"""
    data = _get(
        client, analyst_headers, id_drug=prescribed_drug, id_segment=2
    ).get_json()["data"]

    assert [u["amount"] for u in _by_id(data["units"], "1")] == [0]
    assert [f["amount"] for f in _by_id(data["frequencies"], "3")] == [0]


def test_drug_resources_accepts_the_hospital_variant(client, analyst_headers):
    """GET /drugs/resources/<idHospital> - a rota com hospital devolve o mesmo conteúdo"""
    without_hospital = _get(client, analyst_headers).get_json()["data"]
    with_hospital = _get(client, analyst_headers, id_hospital=SEED_HOSPITAL).get_json()[
        "data"
    ]

    assert with_hospital == without_hospital


def test_drug_resources_returns_an_empty_name_for_an_unknown_drug(
    client, analyst_headers
):
    """GET /drugs/resources - medicamento inexistente devolve nome vazio e o id informado"""
    response = _get(client, analyst_headers, id_drug=999999)

    assert response.status_code == 200
    assert response.get_json()["data"]["drug"] == {"id": 999999, "name": ""}


def test_drug_resources_leaves_routes_and_intervals_empty(client, analyst_headers):
    """GET /drugs/resources - vias e horários só são calculados no modo completo"""
    data = _get(client, analyst_headers).get_json()["data"]

    assert data["routes"] == []
    assert data["intervals"] == []


def test_drug_resources_returns_the_configured_transcription_fields(
    client, analyst_headers
):
    """GET /drugs/resources - devolve os campos extras e removidos configurados na memória"""
    with (
        _memory(MemoryEnum.TRANSCRIPTION_FIELDS.value, '["dose", "peso"]'),
        _memory(MemoryEnum.TRANSCRIPTION_REMOVE_FIELDS.value, '["interval"]'),
    ):
        data = _get(client, analyst_headers).get_json()["data"]

    assert data["extraFields"] == ["dose", "peso"]
    assert data["removeFields"] == ["interval"]


def test_drug_resources_returns_empty_field_lists_without_memory(
    client, analyst_headers
):
    """GET /drugs/resources - sem memória configurada, os campos voltam como listas vazias"""
    with (
        _memory(MemoryEnum.TRANSCRIPTION_FIELDS.value, None),
        _memory(MemoryEnum.TRANSCRIPTION_REMOVE_FIELDS.value, None),
    ):
        data = _get(client, analyst_headers).get_json()["data"]

    assert data["extraFields"] == []
    assert data["removeFields"] == []


def test_drug_resources_requires_prescription_read_permission(
    client, user_manager_headers
):
    """GET /drugs/resources - deve retornar erro [401 UNAUTHORIZED] sem permissão de leitura de prescrição"""
    assert _get(client, user_manager_headers).status_code == 401


def test_frequencies_lists_the_catalogue_sorted_by_description(client, analyst_headers):
    """GET /drugs/frequencies - lista as frequências ordenadas por descrição"""
    response = client.get(FREQUENCIES_URL, headers=analyst_headers)

    assert response.status_code == 200

    data = response.get_json()["data"]
    assert [f["description"] for f in data] == [
        "12h/12h",
        "1x/dia",
        "4h/4h",
        "6h/6h",
        "8h/8h",
    ]
    assert {f["id"] for f in data} == {"1", "2", "3", "4", "6"}


def test_frequencies_does_not_repeat_ids(client, analyst_headers):
    """GET /drugs/frequencies - não repete frequências"""
    data = client.get(FREQUENCIES_URL, headers=analyst_headers).get_json()["data"]

    ids = [f["id"] for f in data]
    assert len(ids) == len(set(ids))


def test_frequencies_requires_prescription_read_permission(
    client, user_manager_headers
):
    """GET /drugs/frequencies - deve retornar erro [401 UNAUTHORIZED] sem permissão de leitura de prescrição"""
    response = client.get(FREQUENCIES_URL, headers=user_manager_headers)

    assert response.status_code == 401


def test_routes_are_empty_when_the_memory_is_absent(client, analyst_headers):
    """GET /lists/routes - sem a memória map-routes, a lista volta vazia"""
    with _memory(MemoryEnum.MAP_ROUTES.value, None):
        response = client.get(ROUTES_URL, headers=analyst_headers)

    assert response.status_code == 200
    assert response.get_json()["data"] == []


def test_routes_returns_the_configured_map_routes(client, analyst_headers):
    """GET /lists/routes - devolve as vias configuradas na memória map-routes"""
    with _memory(
        MemoryEnum.MAP_ROUTES.value,
        '[{"id": "VO", "value": "Via Oral"}, {"id": "IV", "value": "Intravenosa"}]',
    ):
        response = client.get(ROUTES_URL, headers=analyst_headers)

    assert response.status_code == 200
    assert response.get_json()["data"] == [
        {"id": "VO", "name": "Via Oral"},
        {"id": "IV", "name": "Intravenosa"},
    ]


def test_routes_skips_malformed_entries(client, analyst_headers):
    """GET /lists/routes - ignora entradas malformadas da memória map-routes"""
    with _memory(
        MemoryEnum.MAP_ROUTES.value,
        '["VO", {"value": "sem id"}, {"id": "IV", "value": "Intravenosa"}]',
    ):
        response = client.get(ROUTES_URL, headers=analyst_headers)

    assert response.status_code == 200
    assert response.get_json()["data"] == [{"id": "IV", "name": "Intravenosa"}]


def test_routes_requires_basic_features_permission(client):
    """GET /lists/routes - deve retornar erro [401 UNAUTHORIZED] sem permissão básica de leitura"""
    headers = make_headers(get_access(client, roles=[Role.SERVICE_INTEGRATOR.value]))

    response = client.get(ROUTES_URL, headers=headers)

    assert response.status_code == 401
