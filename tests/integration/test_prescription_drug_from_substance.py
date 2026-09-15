"""Integration tests for the substance-backed drug creation performed by
POST /editPrescription/drug (prescription_drug_edit_service).

During conciliation the frontend may send a *substance* (sctid) where a drug id
is expected, because the medication the patient reports taking at home has no
row in the hospital catalogue. The service then materialises a placeholder drug
``[SUB] <substance>`` with id ``900000000000000000 + sctid`` and source
``SUBNH``, seeds its attributes from the substance reference, and links the new
presmed row to it. Subsequent prescriptions for the same substance reuse that
placeholder instead of creating another one.
"""

import pytest
from sqlalchemy import text

from models.main import Drug, DrugAttributes
from models.prescription import PrescriptionDrug
from tests.conftest import session, session_commit
from tests.utils.utils_test_prescription import (
    create_prescription,
    create_prescription_drug,
    test_counters,
)

# ids >= 90000 are wiped by the session-wide cleanup in tests/conftest.py
_SUBSTANCE_ID = 91001
_SUBSTANCE_NAME = "ZZTest Substância Conciliada"
_SUB_DRUG_ID = 900000000000000000 + _SUBSTANCE_ID
_UNKNOWN_ID = 91999
"""An id that is neither a drug nor a substance."""

_SEGMENT_ID = 1  # "Segmento Adulto", so the adult reference columns are used


@pytest.fixture
def seed_substance():
    """Substance with reference values, plus cleanup of the drug it spawns."""

    def _delete():
        session.execute(
            text("DELETE FROM demo.medatributos WHERE fkmedicamento = :id"),
            {"id": _SUB_DRUG_ID},
        )
        session.execute(
            text("DELETE FROM demo.medatributos_audit WHERE fkmedicamento = :id"),
            {"id": _SUB_DRUG_ID},
        )
        session.execute(
            text("DELETE FROM demo.medicamento WHERE fkmedicamento = :id"),
            {"id": _SUB_DRUG_ID},
        )
        session.execute(
            text("DELETE FROM public.substancia WHERE sctid = :id"),
            {"id": _SUBSTANCE_ID},
        )
        session_commit()

    _delete()

    session.execute(
        text(
            "INSERT INTO public.substancia "
            "(sctid, nome, link, ativo, renal_adulto, renal_pediatrico, "
            "plaquetas, gestante, tags) "
            "VALUES (:id, :name, '', true, 30, 99, 50000, 'D', "
            "CAST(:tags AS character varying[]))"
        ),
        {
            "id": _SUBSTANCE_ID,
            "name": _SUBSTANCE_NAME,
            "tags": "{antimicro}",
        },
    )
    session_commit()

    yield

    _delete()


def _new_prescription():
    """Create an empty prescription and return its id."""
    id_prescription = test_counters["id_prescription"]
    admission_number = test_counters["admission_number"]
    test_counters["id_prescription"] += 1
    test_counters["admission_number"] += 1

    create_prescription(
        id=id_prescription,
        admissionNumber=admission_number,
        idPatient=1,
        idSegment=_SEGMENT_ID,
    )
    # getNextId derives the presmed id from the row count, so the prescription
    # needs at least one drug for it to return a value
    create_prescription_drug(
        id=int(f"{id_prescription}500"),
        idPrescription=id_prescription,
        idDrug=3,
    )

    return id_prescription


def _post_drug(client, headers, id_prescription, id_drug):
    """Send the create-drug request for the given (possibly substance) id."""
    return client.post(
        "/editPrescription/drug",
        json={
            "idPrescription": id_prescription,
            "idDrug": id_drug,
            "source": "Medicamentos",
            "dose": 1.0,
            "measureUnit": "1",
            "frequency": "1",
            "route": "VO",
        },
        headers=headers,
    )


def test_create_drug_from_substance_creates_placeholder(
    client, analyst_headers, seed_substance
):
    """A substance id with no drug behind it materialises a [SUB] drug [200 OK]."""
    id_prescription = _new_prescription()

    response = _post_drug(client, analyst_headers, id_prescription, _SUBSTANCE_ID)

    assert response.status_code == 200

    session.expire_all()
    created = session.query(Drug).get(_SUB_DRUG_ID)
    assert created is not None
    assert created.name == f"[SUB] {_SUBSTANCE_NAME}"
    assert created.sctid == _SUBSTANCE_ID
    assert created.source == "SUBNH"


def test_create_drug_from_substance_links_prescription_drug(
    client, analyst_headers, seed_substance
):
    """The new presmed row points at the placeholder, not at the substance id."""
    id_prescription = _new_prescription()

    response = _post_drug(client, analyst_headers, id_prescription, _SUBSTANCE_ID)

    assert response.status_code == 200
    assert response.get_json()["data"]["idDrug"] == _SUB_DRUG_ID

    session.expire_all()
    created = (
        session.query(PrescriptionDrug)
        .filter(PrescriptionDrug.idPrescription == id_prescription)
        .filter(PrescriptionDrug.idDrug == _SUB_DRUG_ID)
        .first()
    )
    assert created is not None


def test_create_drug_from_substance_copies_reference_attributes(
    client, analyst_headers, seed_substance
):
    """Attributes for the prescription's segment are seeded from the substance."""
    id_prescription = _new_prescription()

    response = _post_drug(client, analyst_headers, id_prescription, _SUBSTANCE_ID)

    assert response.status_code == 200

    session.expire_all()
    attributes = (
        session.query(DrugAttributes)
        .filter(DrugAttributes.idDrug == _SUB_DRUG_ID)
        .filter(DrugAttributes.idSegment == _SEGMENT_ID)
        .first()
    )
    assert attributes is not None
    # adult segment, so the adult reference column is the one copied
    assert attributes.kidney == 30
    assert attributes.platelets == 50000
    assert attributes.pregnant == "D"
    assert attributes.antimicro is True
    assert attributes.controlled is False


def test_create_drug_from_substance_reuses_existing_placeholder(
    client, analyst_headers, seed_substance
):
    """A second prescription for the same substance reuses the same drug."""
    first = _new_prescription()
    second = _new_prescription()

    assert _post_drug(client, analyst_headers, first, _SUBSTANCE_ID).status_code == 200
    assert _post_drug(client, analyst_headers, second, _SUBSTANCE_ID).status_code == 200

    session.expire_all()
    placeholders = (
        session.query(Drug)
        .filter(Drug.sctid == _SUBSTANCE_ID)
        .filter(Drug.source == "SUBNH")
        .all()
    )
    assert len(placeholders) == 1
    assert placeholders[0].id == _SUB_DRUG_ID


def test_create_drug_keeps_catalogue_drug_untouched(
    client, analyst_headers, seed_substance
):
    """An id that already is a drug is used as-is — no placeholder is created."""
    id_prescription = _new_prescription()

    response = _post_drug(client, analyst_headers, id_prescription, 5)

    assert response.status_code == 200
    assert response.get_json()["data"]["idDrug"] == 5

    session.expire_all()
    assert session.query(Drug).get(900000000000000000 + 5) is None


def test_create_drug_from_unknown_id_is_rejected(
    client, analyst_headers, seed_substance
):
    """An id matching neither a drug nor a substance is refused [400]."""
    id_prescription = _new_prescription()

    response = _post_drug(client, analyst_headers, id_prescription, _UNKNOWN_ID)

    assert response.status_code == 400

    session.expire_all()
    assert session.query(Drug).get(900000000000000000 + _UNKNOWN_ID) is None
