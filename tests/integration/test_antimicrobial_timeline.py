"""Tests: GET /antimicrobial/timeline/<admission_number>

The endpoint returns the patient header and the antimicrobial courses of one
admission. The grouping rules are covered by tests/unit/test_antimicrobial_timeline.py;
here we pin down what reaches the grouping:

* only drugs flagged ``antimicro`` on the item's segment are listed;
* aggregated and conciliation prescriptions are ignored (they repeat the real
  prescriptions or are not a treatment at all);
* daily prescriptions (segment 1) and CPOE orders (segment 2) both become courses.

Seed data used (demo schema): drug 1 (AMPICILINA + SULBACTAM) is antimicrobial
on segment 1, drug 4 (BISACODIL) is not. Segment 2 is the CPOE segment; the
``cpoe_antimicrobial`` fixture flags drug 1 as antimicrobial there too.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from tests.conftest import session, session_commit
from tests.utils.utils_test_prescription import (
    create_prescription,
    create_prescription_drug,
    test_counters,
)
from utils import status

ADULT_SEGMENT = 1
CPOE_SEGMENT = 2
# a trigger sets the prescription segment from its department (segmentosetor)
DEPARTMENT_BY_SEGMENT = {ADULT_SEGMENT: 1, CPOE_SEGMENT: 3}
ANTIMICROBIAL_DRUG = 1
OTHER_DRUG = 4
PATIENT_ID = 100701


def _url(admission_number):
    """Endpoint URL for an admission"""
    return f"/antimicrobial/timeline/{admission_number}"


def _next_prescription_id():
    """Reserve a unique prescription id"""
    id_prescription = test_counters["id_prescription"]
    test_counters["id_prescription"] += 1
    return id_prescription


@pytest.fixture
def admission():
    """A synthetic patient admitted ten days ago"""
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
            "admission_date": datetime.now() - timedelta(days=10),
        },
    )
    session_commit()

    yield admission_number

    for table in ("pessoa", "pessoa_audit"):
        session.execute(
            text(f"DELETE FROM demo.{table} WHERE nratendimento = :admission"),
            {"admission": admission_number},
        )
    session_commit()


@pytest.fixture
def cpoe_antimicrobial():
    """Flag the antimicrobial drug on the CPOE segment as well"""
    session.execute(
        text(
            "INSERT INTO demo.medatributos (fkmedicamento, idsegmento, antimicro) "
            "VALUES (:id_drug, :id_segment, true)"
        ),
        {"id_drug": ANTIMICROBIAL_DRUG, "id_segment": CPOE_SEGMENT},
    )
    session_commit()

    yield

    for table in ("medatributos_audit", "medatributos"):
        session.execute(
            text(
                f"DELETE FROM demo.{table} "
                "WHERE fkmedicamento = :id_drug AND idsegmento = :id_segment"
            ),
            {"id_drug": ANTIMICROBIAL_DRUG, "id_segment": CPOE_SEGMENT},
        )
    session_commit()


def _prescribe(
    admission_number,
    date,
    expire,
    id_drug=ANTIMICROBIAL_DRUG,
    id_segment=ADULT_SEGMENT,
    agg=None,
    concilia=None,
    suspended=None,
):
    """One prescription holding a single drug"""
    id_prescription = _next_prescription_id()
    create_prescription(
        id=id_prescription,
        admissionNumber=admission_number,
        idPatient=PATIENT_ID,
        idSegment=id_segment,
        idDepartment=DEPARTMENT_BY_SEGMENT[id_segment],
        date=date,
        expire=expire,
        agg=agg,
        concilia=concilia,
    )
    create_prescription_drug(
        id=int(f"{id_prescription}001"),
        idPrescription=id_prescription,
        idDrug=id_drug,
        idSegment=id_segment,
        idMeasureUnit="1",
        idFrequency="3",
        dose=2.0,
        suspendedDate=suspended,
    )
    return id_prescription


def _day(offset):
    """08:00 of today + offset days"""
    return datetime.now().replace(
        hour=8, minute=0, second=0, microsecond=0
    ) + timedelta(days=offset)


def test_requires_read_prescription(client, navigator_headers, admission):
    """401 without READ_PRESCRIPTION"""
    response = client.get(_url(admission), headers=navigator_headers)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_unknown_admission(client, analyst_headers):
    """400 when the admission has no patient nor prescription"""
    response = client.get(_url(999999999), headers=analyst_headers)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.invalidRecord"


def test_admission_without_antimicrobials(client, analyst_headers, admission):
    """The patient header comes back even with no antimicrobial"""
    _prescribe(admission, _day(-1), _day(0), id_drug=OTHER_DRUG)

    response = client.get(_url(admission), headers=analyst_headers)

    assert response.status_code == status.HTTP_200_OK
    data = response.get_json()["data"]
    assert data["courses"] == []
    assert data["patient"]["admissionNumber"] == admission
    assert data["patient"]["idPatient"] == str(PATIENT_ID)
    assert data["patient"]["gender"] == "F"
    assert data["patient"]["weight"] == 70
    assert data["patient"]["segment"] == "Segmento Adulto"


def test_daily_prescriptions_become_one_course(client, analyst_headers, admission):
    """Three daily prescriptions up to today make one active course on D3"""
    for offset in (-2, -1, 0):
        last = _prescribe(admission, _day(offset), _day(offset + 1))

    response = client.get(_url(admission), headers=analyst_headers)

    courses = response.get_json()["data"]["courses"]
    assert len(courses) == 1
    course = courses[0]
    assert course["idDrug"] == ANTIMICROBIAL_DRUG
    assert course["drug"] == "AMPICILINA + SULBACTAM 2 g + 1 g SOL INJ"
    assert course["cpoe"] is False
    assert course["prescriptionCount"] == 3
    assert course["start"] == _day(-2).isoformat()
    assert course["end"] == _day(1).isoformat()
    assert course["lastIdPrescription"] == str(last)
    assert course["regimens"][0]["measureUnit"] == "mg"
    assert course["regimens"][0]["frequency"] == "8h/8h"
    if datetime.now() >= _day(0):
        assert course["status"] == "active"
        assert course["days"] == 3


def test_ignores_agg_concilia_and_other_drugs(client, analyst_headers, admission):
    """Only real prescriptions of antimicrobial drugs count"""
    _prescribe(admission, _day(-5), _day(-4), agg=True)
    _prescribe(admission, _day(-5), _day(-4), concilia="s")
    _prescribe(admission, _day(-5), _day(-4), id_drug=OTHER_DRUG)
    _prescribe(admission, _day(-1), _day(0))

    response = client.get(_url(admission), headers=analyst_headers)

    courses = response.get_json()["data"]["courses"]
    assert len(courses) == 1
    assert courses[0]["start"] == _day(-1).isoformat()
    assert courses[0]["prescriptionCount"] == 1


def test_cpoe_order(client, analyst_headers, admission, cpoe_antimicrobial):
    """A CPOE order is planned to end at its expire date"""
    _prescribe(
        admission, _day(-3), _day(4), id_segment=CPOE_SEGMENT, suspended=_day(-1)
    )

    response = client.get(_url(admission), headers=analyst_headers)

    courses = response.get_json()["data"]["courses"]
    assert len(courses) == 1
    course = courses[0]
    assert course["cpoe"] is True
    assert course["status"] == "suspended"
    assert course["end"] == _day(-1).isoformat()
    assert course["plannedEnd"] == _day(4).isoformat()
    assert course["plannedDays"] == 7
    assert course["days"] == 2
