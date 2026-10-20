"""Tests: GET /infection-control/admission/<admission_number>/cultures

The latest culture of each exam and material of the admission's patient,
released in the last 60 days, with the microorganisms its antibiogram names.
Pinned down here: which culture is the latest (the newest collection, even a
pending one), the freshness cutoff, the patient scope and the payload.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from tests.conftest import session, session_commit
from tests.utils.utils_test_prescription import test_counters
from utils import status

# dedicated ids so the rows never collide with seed data or other tests
PATIENT_ID = 900101
OTHER_PATIENT_ID = 900102
FIRST_HEADER = 900101

BLOOD = "HEMOCULTURA TESTE"
URINE = "UROCULTURA TESTE"
BLOOD_MATERIAL = "SANGUE TESTE"
URINE_MATERIAL = "URINA TESTE"
PENDING = "Coleta de teste aguardando liberação"


def _url(admission_number):
    return f"/infection-control/admission/{admission_number}/cultures"


def _day(offset):
    """08:00 of today + offset days"""
    return datetime.now().replace(
        hour=8, minute=0, second=0, microsecond=0
    ) + timedelta(days=offset)


@pytest.fixture
def admission():
    """A synthetic patient admitted ten days ago, with no culture yet"""
    admission_number = test_counters["admission_number"]
    test_counters["admission_number"] += 1

    session.execute(
        text(
            "INSERT INTO demo.pessoa "
            "(fkpessoa, nratendimento, dtinternacao, dtnascimento, sexo, peso) "
            "VALUES (:id_patient, :admission, :admission_date, '1970-05-04', 'F', 70)"
        ),
        {
            "id_patient": PATIENT_ID,
            "admission": admission_number,
            "admission_date": _day(-10),
        },
    )
    session_commit()

    yield admission_number

    for table in ("pessoa", "pessoa_audit"):
        session.execute(
            text(f"DELETE FROM demo.{table} WHERE nratendimento = :admission"),
            {"admission": admission_number},
        )
    session.execute(
        text("DELETE FROM demo.cultura WHERE fkitemexame >= :first"),
        {"first": FIRST_HEADER},
    )
    session.execute(
        text("DELETE FROM demo.cultura_cabecalho WHERE idculturacab >= :first"),
        {"first": FIRST_HEADER},
    )
    session_commit()


_next_header = {"id": FIRST_HEADER}


def _add_header(
    collected: datetime,
    released: datetime,
    exam: str = BLOOD,
    material: str = BLOOD_MATERIAL,
    gram: str | None = None,
    result: str | None = PENDING,
    id_patient: int = PATIENT_ID,
) -> int:
    """Insert a culture header (demo.cultura_cabecalho); the exam and exam item
    ids mirror its id"""
    id_header = _next_header["id"]
    _next_header["id"] += 1

    session.execute(
        text(
            "INSERT INTO demo.cultura_cabecalho "
            "(idculturacab, fkpessoa, fkexame, fkitemexame, nomeexame, nomematerial, "
            " dtcoleta, dtliberacao, gram, resultprevio) "
            "VALUES (:id, :patient, :id, :id, :exam, :material, "
            " :collected, :released, :gram, :result)"
        ),
        {
            "id": id_header,
            "patient": id_patient,
            "exam": exam,
            "material": material,
            "collected": collected,
            "released": released,
            "gram": gram,
            "result": result,
        },
    )
    session_commit()

    return id_header


def _add_antibiogram(
    id_header: int,
    microorganism: str | None,
    drug: str,
    result: str | None = "S",
    mic: str | None = None,
    prediction: str | None = None,
):
    """Insert an antibiogram row (demo.cultura) of a header"""
    session.execute(
        text(
            "INSERT INTO demo.cultura "
            "(fkexame, fkitemexame, nomemedicamento, nomemicroorganismo, resultado, "
            " qtmicroorganismo, predict, predict_proba) "
            "VALUES (:id, :id, :drug, :microorganism, :result, :mic, :prediction, "
            " :probability)"
        ),
        {
            "id": id_header,
            "drug": drug,
            "microorganism": microorganism,
            "result": result,
            "mic": mic,
            "prediction": prediction,
            "probability": 0.9 if prediction else None,
        },
    )
    session_commit()


def _get(client, headers, admission_number):
    response = client.get(_url(admission_number), headers=headers)
    assert response.status_code == status.HTTP_200_OK
    return response.get_json()["data"]


def test_requires_read_prescription(client, navigator_headers, admission):
    """401 without READ_PRESCRIPTION"""
    response = client.get(_url(admission), headers=navigator_headers)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_unknown_admission(client, analyst_headers):
    """400 when the admission has no patient nor prescription"""
    response = client.get(_url(999999999), headers=analyst_headers)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.invalidRecord"


def test_no_cultures(client, analyst_headers, admission):
    data = _get(client, analyst_headers, admission)

    assert data["admissionNumber"] == admission
    assert data["cultures"] == []


def test_latest_of_each_exam_and_material(client, analyst_headers, admission):
    """The newest collection of each exam and material stands for it, even
    when it is still pending and an older one has a result"""
    _add_header(
        _day(-6),
        _day(-4),
        gram="Bacilos gram negativos (teste)",
        result="<div><label>RESULTADO: </label><span>Positivo</span></div>",
    )
    pending = _add_header(_day(-1), _day(-1))
    # same exam, another material: a culture of its own
    other_material = _add_header(
        _day(-3), _day(-2), material=URINE_MATERIAL, result="Negativo"
    )
    urine = _add_header(
        _day(-5),
        _day(-3),
        exam=URINE,
        material=URINE_MATERIAL,
        gram="Cocos gram positivos (teste)",
        result="Positivo",
    )

    data = _get(client, analyst_headers, admission)

    # newest collection first
    assert [c["id"] for c in data["cultures"]] == [
        str(pending),
        str(other_material),
        str(urine),
    ]

    latest_blood = data["cultures"][0]
    assert latest_blood["examName"] == BLOOD
    assert latest_blood["material"] == BLOOD_MATERIAL
    assert latest_blood["gram"] is None
    assert latest_blood["previousResult"] == PENDING
    assert latest_blood["microorganisms"] == []
    # the dates keep their time of day
    assert latest_blood["collectionDate"] == _day(-1).isoformat()
    assert latest_blood["releaseDate"] == _day(-1).isoformat()

    assert data["cultures"][2]["gram"] == "Cocos gram positivos (teste)"
    assert data["cultures"][2]["previousResult"] == "Positivo"


def test_only_released_in_the_last_60_days(client, analyst_headers, admission):
    """A culture released before the cutoff is left out, and does not hide
    nor stand for its exam and material"""
    _add_header(_day(-70), _day(-61), exam=URINE, material=URINE_MATERIAL)
    fresh = _add_header(_day(-62), _day(-59))

    data = _get(client, analyst_headers, admission)

    assert [c["id"] for c in data["cultures"]] == [str(fresh)]


def test_cultures_of_the_patient_only(client, analyst_headers, admission):
    """Another patient's culture is never shown"""
    _add_header(_day(-2), _day(-1), id_patient=OTHER_PATIENT_ID)

    data = _get(client, analyst_headers, admission)

    assert data["cultures"] == []


def test_microorganisms_of_the_antibiogram(client, analyst_headers, admission):
    """The distinct microorganisms the antibiogram names, sorted; a row with no
    microorganism (a prediction) adds nothing"""
    id_header = _add_header(
        _day(-3),
        _day(-1),
        gram="Bacilos gram negativos (teste)",
        result="Positivo",
    )
    _add_antibiogram(id_header, "Microrganismo B teste", "DROGA A")
    _add_antibiogram(id_header, "Microrganismo B teste", "DROGA B")
    _add_antibiogram(id_header, "Microrganismo A teste", "DROGA A")
    _add_antibiogram(id_header, None, "DROGA C")
    _add_antibiogram(id_header, " ", "DROGA D")

    data = _get(client, analyst_headers, admission)

    assert data["cultures"][0]["microorganisms"] == [
        "Microrganismo A teste",
        "Microrganismo B teste",
    ]


def test_blank_fields_are_none(client, analyst_headers, admission):
    _add_header(_day(-2), _day(-1), gram="  ", result="")

    data = _get(client, analyst_headers, admission)

    assert data["cultures"][0]["gram"] is None
    assert data["cultures"][0]["previousResult"] is None


def _history_url(admission_number, id_culture):
    return f"/infection-control/admission/{admission_number}/cultures/{id_culture}"


def test_history_requires_read_prescription(client, navigator_headers, admission):
    id_culture = _add_header(_day(-2), _day(-1))

    response = client.get(
        _history_url(admission, id_culture), headers=navigator_headers
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_history_of_the_exam_and_material(client, analyst_headers, admission):
    """Every culture of the exam and material, released at any time, newest
    collection first; other exams and materials stay out"""
    old = _add_header(
        _day(-120), _day(-118), gram="Cocos gram positivos (teste)", result="Positivo"
    )
    middle = _add_header(_day(-6), _day(-4), result="Negativo")
    latest = _add_header(_day(-1), _day(-1))
    _add_header(_day(-2), _day(-1), material=URINE_MATERIAL)
    _add_header(_day(-2), _day(-1), exam=URINE, material=URINE_MATERIAL)
    _add_header(_day(-3), _day(-1), id_patient=OTHER_PATIENT_ID)
    _add_antibiogram(old, "Microrganismo teste", "DROGA A")

    response = client.get(_history_url(admission, latest), headers=analyst_headers)

    assert response.status_code == status.HTTP_200_OK
    data = response.get_json()["data"]
    assert data["examName"] == BLOOD
    assert data["material"] == BLOOD_MATERIAL
    assert [c["id"] for c in data["cultures"]] == [
        str(latest),
        str(middle),
        str(old),
    ]
    assert data["cultures"][2]["gram"] == "Cocos gram positivos (teste)"
    assert data["cultures"][2]["microorganisms"] == ["Microrganismo teste"]

    # any culture of the group opens the same history
    response = client.get(_history_url(admission, old), headers=analyst_headers)
    assert [c["id"] for c in response.get_json()["data"]["cultures"]] == [
        str(latest),
        str(middle),
        str(old),
    ]


def test_history_without_material(client, analyst_headers, admission):
    """A culture with no material groups with the ones with no material"""
    first = _add_header(_day(-5), _day(-4), material=None)
    second = _add_header(_day(-2), _day(-1), material=None)
    _add_header(_day(-3), _day(-1))

    response = client.get(_history_url(admission, first), headers=analyst_headers)

    data = response.get_json()["data"]
    assert data["material"] is None
    assert [c["id"] for c in data["cultures"]] == [str(second), str(first)]


def test_history_of_another_patient(client, analyst_headers, admission):
    """The admission on screen never opens another patient's culture"""
    id_culture = _add_header(_day(-2), _day(-1), id_patient=OTHER_PATIENT_ID)

    response = client.get(_history_url(admission, id_culture), headers=analyst_headers)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.invalidRecord"


def test_recent_cultures_without_antibiogram(client, analyst_headers, admission):
    """The card only names the microorganisms: the drugs stay in the history"""
    id_header = _add_header(_day(-3), _day(-1), result="Positivo")
    _add_antibiogram(id_header, "Microrganismo teste", "DROGA A")

    data = _get(client, analyst_headers, admission)

    assert "antibiogram" not in data["cultures"][0]


def test_history_with_the_antibiogram(client, analyst_headers, admission):
    """Each culture of the history carries its released antibiogram, read as
    the culture card reads it, sorted by microorganism and drug"""
    old = _add_header(_day(-20), _day(-18), result="Positivo")
    _add_antibiogram(old, "Microrganismo teste", "DROGA A", result="R")
    latest = _add_header(_day(-3), _day(-1), result="Positivo")
    _add_antibiogram(
        latest, "Microrganismo B teste", "DROGA B", result="Resistente", mic=">=32"
    )
    _add_antibiogram(
        latest,
        "Microrganismo B teste",
        "DROGA A",
        result="Sensível Dose-Dependente",
        mic=" <=0.5 ",
    )
    _add_antibiogram(latest, "Microrganismo A teste", "DROGA C", result="Sensível")
    _add_antibiogram(latest, "Microrganismo A teste", "DROGA D", result="Indeterminado")

    response = client.get(_history_url(admission, latest), headers=analyst_headers)

    data = response.get_json()["data"]
    assert [c["id"] for c in data["cultures"]] == [str(latest), str(old)]
    assert data["cultures"][0]["antibiogram"] == [
        {
            "microorganism": "Microrganismo A teste",
            "drug": "DROGA C",
            "result": "Sensível",
            "resultType": "S",
            "resultDetail": None,
            "mic": None,
        },
        {
            "microorganism": "Microrganismo A teste",
            "drug": "DROGA D",
            "result": "Indeterminado",
            "resultType": "U",
            "resultDetail": "Indeterminado",
            "mic": None,
        },
        {
            "microorganism": "Microrganismo B teste",
            "drug": "DROGA A",
            "result": "Sensível Dose-Dependente",
            "resultType": "S",
            "resultDetail": "Sensível Dose-Dependente",
            "mic": "<=0.5",
        },
        {
            "microorganism": "Microrganismo B teste",
            "drug": "DROGA B",
            "result": "Resistente",
            "resultType": "R",
            "resultDetail": None,
            "mic": ">=32",
        },
    ]
    assert [row["drug"] for row in data["cultures"][1]["antibiogram"]] == ["DROGA A"]
    assert data["cultures"][1]["antibiogram"][0]["resultType"] == "R"


def test_history_antibiogram_leaves_predictions_out(client, analyst_headers, admission):
    """A pending culture has no antibiogram yet: its predictions and blank
    results are never served as the lab's result"""
    pending = _add_header(_day(-1), _day(-1))
    _add_antibiogram(pending, None, "DROGA A", result=None, prediction="R")
    _add_antibiogram(pending, "Microrganismo teste", "DROGA B", result=" ")

    response = client.get(_history_url(admission, pending), headers=analyst_headers)

    assert response.get_json()["data"]["cultures"][0]["antibiogram"] == []
