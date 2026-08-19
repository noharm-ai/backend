"""Tests: GET /reports/culture

The culture report joins microbiology headers with their antibiogram rows and
groups them per (header, microorganism). Grouping, ordering and the prediction
thresholds are the parts worth pinning down.
"""

import pytest
from sqlalchemy import text

from tests.conftest import session, session_commit
from utils import status

URL = "/reports/culture"

# Dedicated ids so the rows never collide with seed data (both tables are empty
# in the seed dump, but the >= 900000 range keeps that true if that changes).
PATIENT_ID = 900001

HEADER_TWO_MICROORGANISMS = 900001  # newest collection date
HEADER_WITH_PREDICTIONS = 900002
HEADER_WITHOUT_CULTURES = 900003  # oldest collection date

DATE_TWO_MICROORGANISMS = "2024-03-12T00:00:00"
DATE_WITH_PREDICTIONS = "2024-03-10T00:00:00"
DATE_WITHOUT_CULTURES = "2024-03-01T00:00:00"


def _add_header(
    id_header: int,
    collection_date: str,
    exam_name: str = "HEMOCULTURA",
    material_name: str = "SANGUE",
    gram: str = "GRAM NEGATIVO",
):
    """Insert a culture header (demo.cultura_cabecalho) for the test patient.

    The exam and exam-item ids mirror the header id, which is what the service
    joins on.
    """
    session.execute(
        text(
            "INSERT INTO demo.cultura_cabecalho "
            "(idculturacab, fkpessoa, fkexame, fkitemexame, nomeexame, nomematerial, "
            " dtcoleta, dtliberacao, gram, dscolonia, resultprevio, complemento) "
            "VALUES (:id, :patient, :id, :id, :exam_name, :material, "
            " :collection_date, :release_date, :gram, 'COLONIA A', 'PREVIO A', 'OBS A')"
        ),
        {
            "id": id_header,
            "patient": PATIENT_ID,
            "exam_name": exam_name,
            "material": material_name,
            "collection_date": collection_date,
            "release_date": collection_date,
            "gram": gram,
        },
    )


def _add_culture(
    id_header: int,
    id_drug: int,
    drug: str,
    id_microorganism: int,
    microorganism: str,
    result: str = "S",
    prediction: str = None,
    predict_proba: float = None,
    drug_proba: float = None,
):
    """Insert an antibiogram row (demo.cultura) attached to a header."""
    session.execute(
        text(
            "INSERT INTO demo.cultura "
            "(fkexame, fkitemexame, fkmedicamento, nomemedicamento, fkmicroorganismo, "
            " nomemicroorganismo, qtmicroorganismo, resultado, predict, predict_proba, "
            " medicamento_proba) "
            "VALUES (:id, :id, :id_drug, :drug, :id_micro, :micro, '10^5', :result, "
            " :prediction, :predict_proba, :drug_proba)"
        ),
        {
            "id": id_header,
            "id_drug": id_drug,
            "drug": drug,
            "id_micro": id_microorganism,
            "micro": microorganism,
            "result": result,
            "prediction": prediction,
            "predict_proba": predict_proba,
            "drug_proba": drug_proba,
        },
    )


def _cleanup():
    """Remove every row created by this module."""
    session.execute(
        text("DELETE FROM demo.cultura WHERE fkexame >= 900000"),
    )
    session.execute(
        text("DELETE FROM demo.cultura_cabecalho WHERE fkpessoa = :patient"),
        {"patient": PATIENT_ID},
    )
    session_commit()


@pytest.fixture(scope="module", autouse=True)
def culture_data():
    """Three headers covering grouping, prediction thresholds and the empty join."""
    _cleanup()

    # --- newest header: two microorganisms under the same exam item ---
    _add_header(HEADER_TWO_MICROORGANISMS, DATE_TWO_MICROORGANISMS)
    _add_culture(
        HEADER_TWO_MICROORGANISMS,
        id_drug=1,
        drug="VANCOMICINA",
        id_microorganism=10,
        microorganism="STAPHYLOCOCCUS AUREUS",
    )
    _add_culture(
        HEADER_TWO_MICROORGANISMS,
        id_drug=2,
        drug="OXACILINA",
        id_microorganism=20,
        microorganism="KLEBSIELLA PNEUMONIAE",
        result="R",
    )

    # --- middle header: one microorganism, three antibiograms with predictions ---
    _add_header(HEADER_WITH_PREDICTIONS, DATE_WITH_PREDICTIONS)
    _add_culture(
        HEADER_WITH_PREDICTIONS,
        id_drug=1,
        drug="MEROPENEM",
        id_microorganism=30,
        microorganism="ESCHERICHIA COLI",
        prediction="R",
        predict_proba=0.9,
        drug_proba=0.5,
    )
    # predict_proba below the 0.6 cutoff — prediction must be dropped
    _add_culture(
        HEADER_WITH_PREDICTIONS,
        id_drug=2,
        drug="AMPICILINA",
        id_microorganism=30,
        microorganism="ESCHERICHIA COLI",
        result="R",
        prediction="R",
        predict_proba=0.4,
        drug_proba=0.5,
    )
    # drug_proba below the 0.007 cutoff — prediction must be dropped
    _add_culture(
        HEADER_WITH_PREDICTIONS,
        id_drug=3,
        drug="CEFEPIMA",
        id_microorganism=30,
        microorganism="ESCHERICHIA COLI",
        prediction="S",
        predict_proba=0.9,
        drug_proba=0.001,
    )

    # --- oldest header: no antibiogram rows at all (outer join) ---
    _add_header(HEADER_WITHOUT_CULTURES, DATE_WITHOUT_CULTURES)

    session_commit()

    yield

    _cleanup()


def _get_report(client, headers, id_patient=PATIENT_ID):
    return client.get(f"{URL}?idPatient={id_patient}", headers=headers)


def _by_key(data):
    return {item["key"]: item for item in data}


def test_culture_report_requires_read_reports(client, navigator_headers):
    """GET /reports/culture - returns 401 for a role without READ_REPORTS"""
    response = _get_report(client, navigator_headers)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_culture_report_without_patient_returns_400(client, analyst_headers):
    """GET /reports/culture - idPatient is mandatory"""
    response = client.get(URL, headers=analyst_headers)

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_culture_report_returns_empty_for_unknown_patient(client, analyst_headers):
    """GET /reports/culture - a patient with no cultures yields an empty list"""
    response = _get_report(client, analyst_headers, id_patient=999999999)

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"] == []


def test_culture_report_orders_by_collection_date_desc(client, analyst_headers):
    """GET /reports/culture - newest collection date comes first"""
    response = _get_report(client, analyst_headers)

    assert response.status_code == status.HTTP_200_OK
    data = response.get_json()["data"]

    assert [item["collectionDate"] for item in data] == [
        DATE_TWO_MICROORGANISMS,
        DATE_TWO_MICROORGANISMS,
        DATE_WITH_PREDICTIONS,
        DATE_WITHOUT_CULTURES,
    ]


def test_culture_report_splits_groups_per_microorganism(client, analyst_headers):
    """GET /reports/culture - one header with two microorganisms yields two groups"""
    data = _get_report(client, analyst_headers).get_json()["data"]
    groups = _by_key(data)

    staph = groups[f"{HEADER_TWO_MICROORGANISMS}-STAPHYLOCOCCUS AUREUS"]
    klebsiella = groups[f"{HEADER_TWO_MICROORGANISMS}-KLEBSIELLA PNEUMONIAE"]

    assert staph["microorganism"] == "STAPHYLOCOCCUS AUREUS"
    assert [c["drug"] for c in staph["cultures"]] == ["VANCOMICINA"]

    assert klebsiella["microorganism"] == "KLEBSIELLA PNEUMONIAE"
    assert [c["drug"] for c in klebsiella["cultures"]] == ["OXACILINA"]
    assert klebsiella["cultures"][0]["result"] == "R"

    # both groups still describe the same header
    assert staph["id"] == klebsiella["id"] == HEADER_TWO_MICROORGANISMS


def test_culture_report_exposes_header_fields(client, analyst_headers):
    """GET /reports/culture - header columns are carried into every group"""
    data = _get_report(client, analyst_headers).get_json()["data"]
    group = _by_key(data)[f"{HEADER_WITH_PREDICTIONS}-ESCHERICHIA COLI"]

    assert group["idExamItem"] == HEADER_WITH_PREDICTIONS
    assert group["examName"] == "HEMOCULTURA"
    assert group["examMaterialName"] == "SANGUE"
    assert group["gram"] == "GRAM NEGATIVO"
    assert group["colony"] == "COLONIA A"
    assert group["previousResult"] == "PREVIO A"
    assert group["extraInfo"] == "OBS A"
    assert group["releaseDate"] == DATE_WITH_PREDICTIONS


def test_culture_report_sorts_antibiograms_by_drug(client, analyst_headers):
    """GET /reports/culture - antibiograms inside a group are sorted by drug name"""
    data = _get_report(client, analyst_headers).get_json()["data"]
    group = _by_key(data)[f"{HEADER_WITH_PREDICTIONS}-ESCHERICHIA COLI"]

    assert [c["drug"] for c in group["cultures"]] == [
        "AMPICILINA",
        "CEFEPIMA",
        "MEROPENEM",
    ]
    assert group["cultures"][0]["microorganismAmount"] == "10^5"


def test_culture_report_keeps_only_confident_predictions(client, analyst_headers):
    """GET /reports/culture - a prediction needs predict_proba > 0.6 and drug_proba > 0.007"""
    data = _get_report(client, analyst_headers).get_json()["data"]
    group = _by_key(data)[f"{HEADER_WITH_PREDICTIONS}-ESCHERICHIA COLI"]

    # AMPICILINA fails the predict_proba cutoff, CEFEPIMA fails the drug_proba one
    assert len(group["predictions"]) == 1
    assert group["predictions"][0]["drug"] == "MEROPENEM"
    assert group["predictions"][0]["prediction"] == "R"
    assert group["predictions"][0]["probability"] == pytest.approx(0.9, abs=1e-6)


def test_culture_report_keeps_headers_without_antibiogram(client, analyst_headers):
    """GET /reports/culture - a header with no culture rows is still reported"""
    data = _get_report(client, analyst_headers).get_json()["data"]
    group = _by_key(data)[f"{HEADER_WITHOUT_CULTURES}-None"]

    assert group["id"] == HEADER_WITHOUT_CULTURES
    assert group["microorganism"] is None
    assert group["cultures"] == []
    assert group["predictions"] == []
