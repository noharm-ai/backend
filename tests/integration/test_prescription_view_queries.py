"""Integration tests for what ``GET /prescriptions/<id>`` reads from the database.

The prescription view is the most used endpoint, so what it has already read is
passed along instead of being read again: the prescription's segment, the
tenant features, the feature flags, the patient's allergy records and the text
columns the models defer. Each of those used to be a query of its own on every
load of the screen; these tests fail when one of them comes back.

They count the statements of a single request, by the table they read. They do
not put a budget on the whole request, which legitimately grows with a new
feature: only the repeated reads are pinned down.
"""

import re

import pytest
from sqlalchemy import event, text
from sqlalchemy.engine import Engine

from tests.conftest import session, session_commit
from tests.integration.test_prescription_interactions import (  # noqa: F401
    _DRUG_A,
    _DRUG_ALLERGEN,
    _DRUG_B,
    _SEED_PATIENT,
    _SUBSTANCE_A,
    _SUBSTANCE_ALLERGEN,
    _SUBSTANCE_B,
    _add_relation,
    _register_allergy,
    seed_substances_and_drugs,  # fixture, asked for by name (usefixtures)
)
from tests.utils import utils_test_prescription

# a seeded prescription whose admission has a patient record
_SEED_PRESCRIPTION = 199
_SEED_ADMISSION = 9999


@pytest.fixture
def statements():
    """The SQL statements executed from the moment the list is cleared"""
    executed = []

    def record(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        """Keeps the statement with its whitespace collapsed"""
        executed.append(" ".join(statement.split()))

    event.listen(Engine, "before_cursor_execute", record)
    try:
        yield executed
    finally:
        event.remove(Engine, "before_cursor_execute", record)


def _view(client, headers, statements: list, id_prescription: int) -> dict:
    """Loads the prescription, leaving in ``statements`` only what the request ran"""
    statements.clear()
    response = client.get(f"/prescriptions/{id_prescription}", headers=headers)
    assert response.status_code == 200

    return response.get_json()["data"]


def _reading(statements: list, table: str) -> list:
    """The statements that read the table (schema.table, as a whole word)"""
    pattern = re.compile(rf"(FROM|JOIN) {re.escape(table)}\b", re.IGNORECASE)

    return [s for s in statements if pattern.search(s)]


def _prescription_with_interaction_and_allergy() -> int:
    """A prescription of two related drugs, for a patient allergic to a third"""
    _add_relation(_SUBSTANCE_A[0], _SUBSTANCE_B[0], "it", "high")
    _add_relation(_SUBSTANCE_A[0], _SUBSTANCE_ALLERGEN[0], "rx", "high")
    _register_allergy(_SEED_PATIENT, _DRUG_ALLERGEN[0])

    prescription = utils_test_prescription.create_basic_prescription()
    base_id = int(f"{prescription.id}010")
    for offset, id_drug in enumerate([_DRUG_A[0], _DRUG_B[0]]):
        utils_test_prescription.create_prescription_drug(
            id=base_id + offset, idPrescription=prescription.id, idDrug=id_drug
        )

    return prescription.id


@pytest.mark.usefixtures("seed_substances_and_drugs")
def test_the_allergy_records_are_read_once(client, analyst_headers, statements):
    """The records confirm the allergy alert, are listed with the notes and
    feed the cross reactivity: one read serves the three"""
    id_prescription = _prescription_with_interaction_and_allergy()

    payload = _view(client, analyst_headers, statements, id_prescription)

    # the cross reactivity did run on those records
    assert payload["alertStats"]["interactions"]["rx"] == 1
    assert payload["alertStats"]["interactions"]["it"] == 1

    assert len(_reading(statements, "demo.alergia")) == 1


@pytest.mark.usefixtures("seed_substances_and_drugs")
def test_the_relations_are_asked_in_one_statement_with_no_ids_in_its_text(
    client, analyst_headers, statements
):
    """The substance pairs go as parameters: the statement is the same for
    every prescription, whatever its items"""
    id_prescription = _prescription_with_interaction_and_allergy()

    _view(client, analyst_headers, statements, id_prescription)

    relations = _reading(statements, "public.relacao")
    assert len(relations) == 1
    assert str(_SUBSTANCE_A[0]) not in relations[0]
    assert "values" not in relations[0].lower()


def test_the_segment_and_the_features_are_not_read_again(
    client, analyst_headers, statements
):
    """The segment comes joined to the prescription and the tenant features
    with the other memory items: the checks that follow reuse them"""
    _view(client, analyst_headers, statements, _SEED_PRESCRIPTION)

    assert len(_reading(statements, "demo.segmento")) == 1
    assert len(_reading(statements, "demo.memoria")) == 1


def test_the_feature_flags_are_read_once(client, analyst_headers, statements):
    """Each cache of the view (clinical notes, exams) checks a feature flag:
    one read answers them all, also when no flag is set"""
    _view(client, analyst_headers, statements, _SEED_PRESCRIPTION)

    assert len(_reading(statements, "public.memoria")) == 1


def test_the_deferred_texts_come_with_the_prescription(
    client, analyst_headers, statements
):
    """The prescription notes and the patient's observation and alert are
    deferred in the models; the view shows the three, so it loads them with
    the prescription instead of one query each"""
    session.execute(
        text(
            "UPDATE demo.prescricao SET evolucao = 'evolução da prescrição' "
            "WHERE fkprescricao = :id"
        ),
        {"id": _SEED_PRESCRIPTION},
    )
    session.execute(
        text(
            "UPDATE demo.pessoa SET anotacao = 'anotação do paciente', "
            "alertatexto = 'alerta do paciente' WHERE nratendimento = :admission"
        ),
        {"admission": _SEED_ADMISSION},
    )
    session_commit()

    try:
        payload = _view(client, analyst_headers, statements, _SEED_PRESCRIPTION)
    finally:
        session.execute(
            text("UPDATE demo.prescricao SET evolucao = NULL WHERE fkprescricao = :id"),
            {"id": _SEED_PRESCRIPTION},
        )
        session.execute(
            text(
                "UPDATE demo.pessoa SET anotacao = NULL, alertatexto = NULL "
                "WHERE nratendimento = :admission"
            ),
            {"admission": _SEED_ADMISSION},
        )
        session_commit()

    assert payload["notes"] == "evolução da prescrição"
    assert payload["observation"] == "anotação do paciente"
    assert payload["alert"] == "alerta do paciente"

    columns = [
        "demo.prescricao.evolucao",
        "demo.pessoa.anotacao",
        "demo.pessoa.alertatexto",
    ]

    # the three come in the statement that reads the prescription and its patient
    prescription = _reading(statements, "demo.prescricao")[0]
    assert "JOIN demo.pessoa" in prescription
    assert all(column in prescription for column in columns)

    # and none is loaded on its own afterwards (a deferred column read on
    # access is a statement selecting that column alone)
    for column in columns:
        assert not [s for s in statements if s.startswith(f"SELECT {column} ")], column
