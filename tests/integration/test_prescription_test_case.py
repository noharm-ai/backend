"""Integration tests for ``POST /prescriptions/test-case``: maintainers create
prescriptions in a schema with the PRESCRIPTION_TEST_CASE feature, inserted
through the database triggers as the hospital's, with prescalc run on them
right away.

The tests run in demo, so the feature is turned on there by the
``test_case_schema`` fixture. Every row a test creates is deleted by the
``created`` fixture.
"""

import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from config import Config
from models.enums import FeatureEnum, NoHarmENV
from security.role import Role
from tests.conftest import get_access, make_headers, session, session_commit
from utils import prescriptionutils

_URL = "/prescriptions/test-case"

# demo seed: departments 1 and 2 are in segment 1, department 3 in the CPOE
# segment 2, department 4 has no segment
_DEPARTMENT = 1
_CPOE_DEPARTMENT = 3
_DEPARTMENT_WITHOUT_SEGMENT = 4
_SEGMENT = 1
_CPOE_SEGMENT = 2


@pytest.fixture
def maintainer_headers(client):
    """Headers with CURATOR role, which holds the MAINTAINER permission"""
    return make_headers(get_access(client, roles=[Role.CURATOR.value]))


_FEATURE = FeatureEnum.PRESCRIPTION_TEST_CASE.value


def _read_features():
    """The feature list stored in the demo schema"""
    row = session.execute(
        text("SELECT valor FROM demo.memoria WHERE tipo = 'features'")
    ).first()
    return list(row[0]) if row else []


def _write_features(features):
    """Overwrite the demo schema feature list"""
    session.execute(
        text(
            "UPDATE demo.memoria SET valor = CAST(:value AS json) WHERE tipo = 'features'"
        ),
        {"value": json.dumps(features)},
    )
    session_commit()


@pytest.fixture
def features():
    """Sets whether demo has the test case feature, restoring its list after"""
    session.rollback()
    original = _read_features()
    others = [feature for feature in original if feature != _FEATURE]

    def _set(enabled: bool):
        _write_features(others + [_FEATURE] if enabled else others)

    yield _set

    session.rollback()
    _write_features(original)


@pytest.fixture
def test_case_schema(features):
    """demo is a test case schema: it has the feature"""
    features(True)


@pytest.fixture
def created():
    """Collects what the tests create (prescriptions and admissions) and
    deletes it afterwards, with what prescalc made of it"""
    data = {"prescriptions": [], "admissions": []}
    yield data

    session.rollback()
    for admission_number in data["admissions"]:
        params = {"admission_number": admission_number}
        session.execute(
            text(
                "DELETE FROM demo.presmed_audit WHERE fkpresmed IN ("
                " SELECT pm.fkpresmed FROM demo.presmed pm"
                " JOIN demo.prescricao p ON p.fkprescricao = pm.fkprescricao"
                " WHERE p.nratendimento = :admission_number)"
            ),
            params,
        )
        session.execute(
            text(
                "DELETE FROM demo.presmed WHERE fkprescricao IN ("
                " SELECT fkprescricao FROM demo.prescricao"
                " WHERE nratendimento = :admission_number)"
            ),
            params,
        )
        for table in (
            "prescricao_audit",
            "prescricao",
            "fila_atendimento",
            "pessoa_audit",
            "pessoa",
        ):
            session.execute(
                text(
                    f"DELETE FROM demo.{table} WHERE nratendimento = :admission_number"
                ),
                params,
            )
    for id_prescription in data["prescriptions"]:
        params = {"id": id_prescription}
        session.execute(
            text(
                "DELETE FROM demo.presmed_audit WHERE fkpresmed IN ("
                " SELECT fkpresmed FROM demo.presmed WHERE fkprescricao = :id)"
            ),
            params,
        )
        session.execute(
            text("DELETE FROM demo.presmed WHERE fkprescricao = :id"), params
        )
        session.execute(
            text("DELETE FROM demo.prescricao_audit WHERE fkprescricao = :id"), params
        )
        session.execute(
            text("DELETE FROM demo.prescricao WHERE fkprescricao = :id"), params
        )
    session_commit()


def _payload(**overrides) -> dict:
    payload = {
        "idDepartment": _DEPARTMENT,
        "bed": "T-01",
        "prescriber": "Fulano Beltrano",
        "patient": {
            "birthdate": "1950-05-10",
            "gender": "F",
            "weight": 62.5,
            "height": 160,
        },
        "items": [
            {
                "idDrug": 2,
                "dose": 100,
                "measureUnit": "1",
                "frequency": "3",
                "route": "VO",
                "interval": "08 16 24",
            },
            {"idDrug": 3, "dose": 10, "measureUnit": "1", "frequency": "1"},
        ],
    }
    payload.update(overrides)
    return payload


def _create(client, headers, created: dict, payload: dict, new_admission=True):
    response = client.post(_URL, json=payload, headers=headers)
    assert response.status_code == 200, response.get_json()

    data = response.get_json()["data"]
    created["prescriptions"].append(int(data["idPrescription"]))
    if new_admission:
        created["admissions"].append(data["admissionNumber"])

    return data


def _query(sql: str, **params):
    session.rollback()
    return session.execute(text(sql), params)


def test_only_maintainers_can_create_test_cases(
    client, analyst_headers, test_case_schema
):
    """A pharmacist cannot create a test case"""
    response = client.post(_URL, json=_payload(), headers=analyst_headers)

    assert response.status_code == 401


def test_test_cases_are_not_created_in_production(
    client, maintainer_headers, test_case_schema, monkeypatch
):
    """The route is not served in production, even to a maintainer of a test
    case schema"""
    last_prescription = _query("SELECT max(fkprescricao) FROM demo.prescricao").scalar()
    monkeypatch.setattr(Config, "ENV", NoHarmENV.PRODUCTION.value)

    response = client.post(_URL, json=_payload(), headers=maintainer_headers)

    assert response.status_code == 401
    assert (
        _query("SELECT max(fkprescricao) FROM demo.prescricao").scalar()
        == last_prescription
    )


def test_test_cases_are_only_created_in_the_test_schema(
    client, maintainer_headers, features
):
    """Without the feature nothing is created, even by a maintainer"""
    features(False)
    last_prescription = _query("SELECT max(fkprescricao) FROM demo.prescricao").scalar()

    response = client.post(_URL, json=_payload(), headers=maintainer_headers)

    assert response.status_code == 400
    assert (
        _query("SELECT max(fkprescricao) FROM demo.prescricao").scalar()
        == last_prescription
    )


def test_new_admission_is_completed_by_the_triggers_and_processed(
    client, maintainer_headers, test_case_schema, created
):
    """A new admission with the patient's data; the prescription and items
    are completed by the triggers and prescalc puts them in a prescription-day"""
    prescription_date = datetime.today().replace(microsecond=0)
    data = _create(
        client,
        maintainer_headers,
        created,
        _payload(date=prescription_date.isoformat()),
    )

    admission_number = data["admissionNumber"]
    id_prescription = int(data["idPrescription"])

    patient = _query(
        "SELECT fkpessoa, dtnascimento, sexo, peso, altura, fksetor, leito, dtinternacao"
        " FROM demo.pessoa WHERE nratendimento = :n",
        n=admission_number,
    ).one()
    assert str(patient.fkpessoa) == data["idPatient"]
    assert patient.dtnascimento.isoformat() == "1950-05-10"
    assert patient.sexo == "F"
    assert patient.peso == 62.5
    assert patient.altura == 160
    assert patient.fksetor == _DEPARTMENT
    assert patient.leito == "T-01"
    assert patient.dtinternacao == prescription_date

    prescription = _query(
        "SELECT fkpessoa, idsegmento, fksetor, dtvigencia, prescritor, indicadores"
        " FROM demo.prescricao WHERE fkprescricao = :id",
        id=id_prescription,
    ).one()
    # segment set by the trigger from the department
    assert prescription.idsegmento == _SEGMENT
    assert data["idSegment"] == _SEGMENT
    assert prescription.fksetor == _DEPARTMENT
    assert prescription.dtvigencia == prescription_date + timedelta(days=1)
    assert prescription.prescritor == "Fulano Beltrano"
    # processed by prescalc
    assert prescription.indicadores is not None

    items = _query(
        "SELECT fkpresmed, fkmedicamento, doseconv, frequenciadia, idsegmento, origem,"
        " horario, via FROM demo.presmed WHERE fkprescricao = :id ORDER BY fkpresmed",
        id=id_prescription,
    ).all()
    assert [str(i.fkpresmed) for i in items] == data["items"]
    assert [i.fkpresmed for i in items] == [
        id_prescription * 1000,
        id_prescription * 1000 + 1,
    ]
    assert [i.fkmedicamento for i in items] == [2, 3]
    # computed by the presmed trigger from the frequency record
    assert [i.frequenciadia for i in items] == [3, 1]
    assert [i.idsegmento for i in items] == [_SEGMENT, _SEGMENT]
    assert items[0].doseconv == 100
    assert items[0].origem == "Medicamentos"
    assert items[0].horario == "08 16 24"
    assert items[0].via == "VO"

    id_prescription_day = prescriptionutils.gen_agg_id(
        admission_number, _SEGMENT, prescription_date
    )
    assert data["idPrescriptionDay"] == str(id_prescription_day)
    prescription_day = _query(
        "SELECT agregada, aggmedicamento, indicadores"
        " FROM demo.prescricao WHERE fkprescricao = :id",
        id=id_prescription_day,
    ).one()
    assert prescription_day.agregada is True
    assert sorted(prescription_day.aggmedicamento) == [2, 3]
    assert prescription_day.indicadores is not None

    # the items are processed: prescalc central would not pick them again
    processed = _query(
        "SELECT count(*) FROM demo.presmed_audit"
        " WHERE fkpresmed = ANY(:ids) AND tp_audit = 1",
        ids=[i.fkpresmed for i in items],
    ).scalar()
    assert processed == 2


def test_prescalc_runs_as_the_static_user(
    client, maintainer_headers, test_case_schema, created
):
    """The prescription-day is created by the static user, as prescalc central
    would, not by the maintainer"""
    data = _create(client, maintainer_headers, created, _payload())

    created_by = (
        _query(
            "SELECT created_by FROM demo.prescricao_audit WHERE fkprescricao = :id",
            id=int(data["idPrescriptionDay"]),
        )
        .scalars()
        .all()
    )
    assert created_by
    assert set(created_by) == {0}


def test_existing_admission_gets_a_new_prescription(
    client, maintainer_headers, test_case_schema, created
):
    """With an admission number, the prescription is for that patient and no
    admission is created"""
    first = _create(client, maintainer_headers, created, _payload())
    patients = _query("SELECT count(*) FROM demo.pessoa").scalar()

    second = _create(
        client,
        maintainer_headers,
        created,
        _payload(
            admissionNumber=first["admissionNumber"],
            patient=None,
            items=[{"idDrug": 4, "dose": 5, "measureUnit": "1", "frequency": "1"}],
        ),
        new_admission=False,
    )

    assert second["admissionNumber"] == first["admissionNumber"]
    assert second["idPatient"] == first["idPatient"]
    assert int(second["idPrescription"]) > int(first["idPrescription"])
    assert _query("SELECT count(*) FROM demo.pessoa").scalar() == patients

    # same day: both prescriptions are in the same prescription-day
    assert second["idPrescriptionDay"] == first["idPrescriptionDay"]
    drugs = _query(
        "SELECT aggmedicamento FROM demo.prescricao WHERE fkprescricao = :id",
        id=int(second["idPrescriptionDay"]),
    ).scalar()
    assert sorted(drugs) == [2, 3, 4]


def test_unknown_admission_is_refused(client, maintainer_headers, test_case_schema):
    """An admission number that does not exist is not created"""
    response = client.post(
        _URL,
        json=_payload(admissionNumber=999_999_998, patient=None),
        headers=maintainer_headers,
    )

    assert response.status_code == 400
    assert response.get_json()["message"] == "Atendimento inexistente"


def test_cpoe_department_creates_the_day_of_the_admission(
    client, maintainer_headers, test_case_schema, created
):
    """In a CPOE segment prescalc runs by admission and date"""
    prescription_date = datetime.today().replace(microsecond=0)
    data = _create(
        client,
        maintainer_headers,
        created,
        _payload(idDepartment=_CPOE_DEPARTMENT, date=prescription_date.isoformat()),
    )

    assert data["idSegment"] == _CPOE_SEGMENT
    id_prescription_day = prescriptionutils.gen_agg_id(
        data["admissionNumber"], _CPOE_SEGMENT, prescription_date.date()
    )
    assert data["idPrescriptionDay"] == str(id_prescription_day)
    drugs = _query(
        "SELECT aggmedicamento FROM demo.prescricao WHERE fkprescricao = :id",
        id=id_prescription_day,
    ).scalar()
    assert sorted(drugs) == [2, 3]


def test_item_kind_is_kept_without_a_schema_mapping(
    client, maintainer_headers, test_case_schema, created
):
    """demo maps no origem value to solutions: the chosen kind is kept anyway"""
    data = _create(
        client,
        maintainer_headers,
        created,
        _payload(
            items=[
                {
                    "idDrug": 6,
                    "source": "Soluções",
                    "dose": 10,
                    "measureUnit": "1",
                    "frequency": "1",
                }
            ]
        ),
    )

    origin = _query(
        "SELECT origem FROM demo.presmed WHERE fkprescricao = :id",
        id=int(data["idPrescription"]),
    ).scalar()
    assert origin == "Soluções"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"idDepartment": _DEPARTMENT_WITHOUT_SEGMENT}, "Setor sem segmento"),
        ({"items": [{"idDrug": 987654321}]}, "Medicamento inexistente: 987654321"),
        (
            {"items": [{"idDrug": 2, "measureUnit": "zz-unknown"}]},
            "Unidade de medida inexistente: zz-unknown",
        ),
        (
            {"items": [{"idDrug": 2, "frequency": "zz-unknown"}]},
            "Frequência inexistente: zz-unknown",
        ),
        (
            {
                "date": "2026-01-10T10:00:00",
                "expire": "2026-01-09T10:00:00",
            },
            "A vigência deve ser posterior à data da prescrição",
        ),
    ],
)
def test_invalid_test_cases_are_refused(
    client, maintainer_headers, test_case_schema, overrides, message
):
    """Nothing is created when the department, an item or the dates are invalid"""
    last_prescription = _query("SELECT max(fkprescricao) FROM demo.prescricao").scalar()

    response = client.post(_URL, json=_payload(**overrides), headers=maintainer_headers)

    assert response.status_code == 400
    assert response.get_json()["message"] == message
    assert (
        _query("SELECT max(fkprescricao) FROM demo.prescricao").scalar()
        == last_prescription
    )


def test_a_prescription_needs_items(client, maintainer_headers, test_case_schema):
    """No items: refused by the request validation"""
    response = client.post(_URL, json=_payload(items=[]), headers=maintainer_headers)

    assert response.status_code == 400
